"""Phase 4: Revenue OS structure + canonical revenue_* projection + reconciliation.

Proves the new Revenue OS layer produces outcomes equivalent to the existing,
tested Revenue Factory -- so production traffic can be switched only after parity.
"""

import agents.revenue as revenue_agents
import aion_revenue_factory as arf
import apps.revenue as revenue_app
from aion_revenue_factory import Dashboard, RevenueFactory
from aion_revenue_factory.integrations import CollectingSink
from aion_revenue_factory.integrations.aion_events import validate_event
from integrations.revenue import SupabaseRevenueAdapter


# -- structure / facades (no fork, no duplication) ------------------------

def test_apps_facade_is_the_same_factory():
    assert revenue_app.RevenueFactory is arf.RevenueFactory
    assert revenue_app.Dashboard is arf.Dashboard


def test_agents_facade_exposes_the_eight_departments():
    for name in (
        "OpportunityDiscovery", "OfferIntelligence", "OutreachWorkforce",
        "MeetingPrep", "ProposalGenerator", "DealCoach", "CustomerSuccess",
        "LearningEngine",
    ):
        assert hasattr(revenue_agents, name)


# -- reconciliation: old (InMemoryCRM) vs new (SupabaseRevenueAdapter) -----

def test_supabase_adapter_gives_identical_results_and_metrics():
    f_base = RevenueFactory()
    f_base.run_days(5, prospects=50)
    m_base = Dashboard(f_base.crm).metrics()

    f_new = RevenueFactory(crm=SupabaseRevenueAdapter())
    f_new.run_days(5, prospects=50)
    m_new = Dashboard(f_new.crm).metrics()

    # The adapter reads exactly like InMemoryCRM -> byte-equal outcomes.
    assert m_base == m_new


def test_adapter_projects_canonical_revenue_rows():
    adapter = SupabaseRevenueAdapter()
    RevenueFactory(crm=adapter).run_days(5, prospects=50)

    leads = adapter.rows_for("revenue_leads")
    assert leads
    for r in leads:
        assert r["source_system"] == "aion_revenue_factory"
        assert "lead_id" in r and "company" in r and "lead_score" in r

    deals = adapter.rows_for("revenue_deals")
    assert deals
    for r in deals:
        assert "deal_id" in r and "deal_value" in r and "deal_stage" in r

    # Won deals produce both an outcome and a revenue event.
    outcomes = adapter.rows_for("revenue_outcomes")
    if outcomes:
        assert adapter.rows_for("revenue_events")
        for r in adapter.rows_for("revenue_events"):
            assert r["revenue_event"] == "revenue.collected"


def test_no_new_tables_only_canonical_revenue_tables():
    adapter = SupabaseRevenueAdapter()
    RevenueFactory(crm=adapter).run_days(3, prospects=40)
    canonical = {
        "revenue_leads", "revenue_deals", "revenue_proposals",
        "revenue_discovery_calls", "revenue_activities", "revenue_outcomes",
        "revenue_events",
    }
    used = {t for t, _ in adapter.persisted}
    assert used <= canonical


# -- revenue lifecycle events (every important transition emits) -----------

def test_revenue_lifecycle_events_are_emitted_and_valid():
    sink = CollectingSink()
    RevenueFactory(event_sink=sink).run_days(7, prospects=50)
    types = set(sink.types())
    assert "proposal.sent" in types
    assert "deal.won" in types
    assert "revenue.collected" in types
    for ev in sink.events:
        assert validate_event(ev) == []


def test_events_do_not_change_determinism():
    base = RevenueFactory().run_days(4, prospects=40)
    sink = CollectingSink()
    withsink = RevenueFactory(event_sink=sink).run_days(4, prospects=40)
    assert [r.revenue for r in base] == [r.revenue for r in withsink]
    assert [r.won for r in base] == [r.won for r in withsink]
