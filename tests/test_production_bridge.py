"""Phase 5 -- production write-through bridge test matrix.

Proves the production adapter's semantics against ``InMemoryCanonicalWriter``,
which models the live ``revenue_*`` constraints discovered by read-only Supabase
inspection. No live database is touched; the live canary is gated separately.
"""

import pytest

from aion_revenue_factory import RevenueFactory
from integrations.revenue.production_bridge import (
    ConcurrencyConflict,
    DownstreamWriteError,
    ForeignKeyError,
    InMemoryCanonicalWriter,
    ProductionSupabaseRevenueAdapter,
    RestCanonicalWriter,
    build_idempotency_key,
)
from integrations.revenue.supabase_revenue import (
    CanonicalValidationError,
    _deal_row,
    _lead_row,
    validate_canonical_row,
)
from aion_revenue_factory.domain.models import Contact, Deal, Opportunity, Scores


def _opp(name="Acme", oid=None):
    o = Opportunity(name=name, industry="saas", contact=Contact("A", "CEO", "a@x.co"),
                    scores=Scores(revenue_score=80, buying_intent=70,
                                  estimated_contract_value=60_000))
    if oid:
        o.id = oid
    return o


# -- 1. create -------------------------------------------------------------

def test_create_writes_canonical_row_and_outbox_event():
    w = InMemoryCanonicalWriter()
    w.write("revenue_leads", _lead_row(_opp(oid="opp_create1")),
            idempotency_key="k1", entity_type="lead", entity_id="opp_create1")
    assert "opp_create1" in w.tables["revenue_leads"]
    assert len(w.sync_events) == 1
    ev = w.sync_events[0]
    # outbox NOT NULL contract satisfied
    for col in ("entity_type", "entity_id", "source_system", "event_type",
                "payload", "previous_version", "new_version", "actor_type",
                "actor_id", "supabase_record_id", "idempotency_key"):
        assert ev[col] is not None


# -- 2. update -------------------------------------------------------------

def test_update_bumps_version_and_emits_second_event():
    w = InMemoryCanonicalWriter()
    o = _opp(oid="opp_upd")
    r1 = w.write("revenue_leads", _lead_row(o), idempotency_key="k1",
                 entity_type="lead", entity_id="opp_upd")
    o.website = "https://changed.example"
    r2 = w.write("revenue_leads", _lead_row(o), idempotency_key="k2",
                 entity_type="lead", entity_id="opp_upd")
    assert r1.version == 1 and r2.version == 2
    assert r2.created is False
    assert len(w.tables["revenue_leads"]) == 1  # same entity, one row
    assert len(w.sync_events) == 2


# -- 3 & 4. duplicate / idempotent retry -----------------------------------

def test_duplicate_idempotency_key_is_a_noop_duplicate():
    w = InMemoryCanonicalWriter()
    row = _lead_row(_opp(oid="opp_dup"))
    r1 = w.write("revenue_leads", row, idempotency_key="same",
                 entity_type="lead", entity_id="opp_dup")
    r2 = w.write("revenue_leads", row, idempotency_key="same",
                 entity_type="lead", entity_id="opp_dup")
    assert r1 is r2  # exact same result object returned
    assert len(w.tables["revenue_leads"]) == 1
    assert len(w.sync_events) == 1  # no duplicate outbox row


def test_deterministic_idempotency_key_stable_and_content_sensitive():
    o = _opp(oid="opp_key")
    k1 = build_idempotency_key("revenue_leads", _lead_row(o))
    k2 = build_idempotency_key("revenue_leads", _lead_row(o))
    assert k1 == k2  # same content -> same key
    o.website = "https://other.example"
    assert build_idempotency_key("revenue_leads", _lead_row(o)) != k1


# -- 5. optimistic concurrency ---------------------------------------------

def test_stale_expected_version_conflicts_and_writes_nothing():
    w = InMemoryCanonicalWriter()
    o = _opp(oid="opp_cc")
    w.write("revenue_leads", _lead_row(o), idempotency_key="k1",
            entity_type="lead", entity_id="opp_cc")  # -> version 1
    with pytest.raises(ConcurrencyConflict):
        w.write("revenue_leads", _lead_row(o), idempotency_key="k2",
                entity_type="lead", entity_id="opp_cc", expected_version=0)
    assert w.versions[("revenue_leads", "opp_cc")] == 1  # unchanged
    assert len(w.sync_events) == 1


def test_correct_expected_version_succeeds():
    w = InMemoryCanonicalWriter()
    o = _opp(oid="opp_cc2")
    w.write("revenue_leads", _lead_row(o), idempotency_key="k1",
            entity_type="lead", entity_id="opp_cc2")
    r = w.write("revenue_leads", _lead_row(o), idempotency_key="k2",
                entity_type="lead", entity_id="opp_cc2", expected_version=1)
    assert r.version == 2


# -- 6. invalid input ------------------------------------------------------

def test_missing_required_not_null_is_rejected_before_write():
    w = InMemoryCanonicalWriter()
    bad = _deal_row(Deal(opportunity_id="opp_x"))
    del bad["deal_name"]  # NOT NULL on the live table
    with pytest.raises(CanonicalValidationError):
        w.write("revenue_deals", bad, idempotency_key="k",
                entity_type="deal", entity_id=bad["deal_id"])
    assert "revenue_deals" not in w.tables or not w.tables["revenue_deals"]


def test_non_canonical_table_is_rejected():
    with pytest.raises(CanonicalValidationError):
        validate_canonical_row("opportunities", {"id": "x"})


# -- 7. relationship integrity ---------------------------------------------

def test_child_before_parent_is_rejected_no_orphan():
    w = InMemoryCanonicalWriter()
    deal = Deal(opportunity_id="opp_missing")
    with pytest.raises(ForeignKeyError):
        w.write("revenue_deals", _deal_row(deal), idempotency_key="k",
                entity_type="deal", entity_id=deal.id)
    assert not w.tables.get("revenue_deals")


def test_child_after_parent_succeeds():
    w = InMemoryCanonicalWriter()
    o = _opp(oid="opp_parent")
    w.write("revenue_leads", _lead_row(o), idempotency_key="k1",
            entity_type="lead", entity_id="opp_parent")
    deal = Deal(opportunity_id="opp_parent")
    r = w.write("revenue_deals", _deal_row(deal), idempotency_key="k2",
                entity_type="deal", entity_id=deal.id)
    assert r.created


# -- 8. rollback / downstream failure --------------------------------------

def test_downstream_failure_leaves_no_partial_row():
    w = InMemoryCanonicalWriter(fail_table="revenue_leads")
    o = _opp(oid="opp_fail")
    with pytest.raises(DownstreamWriteError):
        w.write("revenue_leads", _lead_row(o), idempotency_key="k",
                entity_type="lead", entity_id="opp_fail")
    assert not w.tables.get("revenue_leads")
    assert not w.sync_events
    # the idempotency key was NOT consumed -> a retry can succeed
    r = w.write("revenue_leads", _lead_row(o), idempotency_key="k",
                entity_type="lead", entity_id="opp_fail")
    assert r.created


# -- 9. adapter refuses non-canonical + never targets legacy ---------------

def test_adapter_only_targets_canonical_tables():
    adapter = ProductionSupabaseRevenueAdapter(InMemoryCanonicalWriter(strict_fk=False))
    RevenueFactory(crm=adapter).run_days(3, prospects=40)
    used = {t for t, _ in adapter.persisted}
    assert used <= {
        "revenue_leads", "revenue_deals", "revenue_proposals",
        "revenue_discovery_calls", "revenue_activities", "revenue_outcomes",
        "revenue_events",
    }
    assert "opportunities" not in used and "deals" not in used


# -- 8 (flow) + 9 (idempotency) end-to-end offline canary dry-run ----------

def test_full_run_projects_and_is_replay_idempotent():
    writer = InMemoryCanonicalWriter(strict_fk=False)
    adapter = ProductionSupabaseRevenueAdapter(writer)
    RevenueFactory(crm=adapter).run_days(5, prospects=50)

    assert writer.tables.get("revenue_leads")          # leads created
    assert writer.sync_events                           # outbox populated
    leads_after_first = len(writer.tables["revenue_leads"])
    events_after_first = len(writer.sync_events)

    # Replay the exact same rows through the same writer -> all duplicates,
    # no new canonical rows, no new outbox events.
    from integrations.revenue.production_bridge import ENTITY_TYPE
    from integrations.revenue.supabase_revenue import BUSINESS_KEY
    replay = [(t, r) for t, r in adapter.persisted]
    for table, row in replay:
        writer.write(table, row,
                     idempotency_key=build_idempotency_key(table, row),
                     entity_type=ENTITY_TYPE[table],
                     entity_id=row[BUSINESS_KEY[table]])
    assert len(writer.tables["revenue_leads"]) == leads_after_first
    assert len(writer.sync_events) == events_after_first


# -- security: no service-role key; missing secret is reported not invented -

def test_rest_writer_requires_a_token_and_never_fakes_one():
    with pytest.raises(RuntimeError) as exc:
        RestCanonicalWriter("https://example/canonical-write", token=None)
    assert "SECRET_REQUIRED: REVENUE_INGEST_API_KEY" in str(exc.value)
