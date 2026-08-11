"""SQL operational store: durability, DB-enforced idempotency, drop-in parity.

These run against SqliteOutreachStore, which shares the *identical* SQL code
path with PostgresOutreachStore (only the parameter placeholder differs). So a
green run here exercises the same INSERT/ON CONFLICT/SELECT statements Postgres
will run in production.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone

import pytest

from aion_revenue_factory.outreach import (
    Campaign,
    CampaignLead,
    CampaignState,
    EmailEvent,
    EmailMessage,
    EventType,
    Lead,
    LeadCampaignState,
    OutreachConfig,
    OutreachStore,
    OutreachSystem,
    QueueItem,
    QueueStatus,
    SqliteOutreachStore,
    SuppressionEntry,
    SuppressionReason,
)
from aion_revenue_factory.outreach.stores import POSTGRES, SqlOutreachStore
from aion_revenue_factory.outreach.wiring import (
    _build_operational_store,
    describe_outreach_wiring,
)

from .conftest import IN_WINDOW


@pytest.fixture
def store():
    return SqliteOutreachStore(":memory:")


def test_satisfies_protocol(store):
    assert isinstance(store, OutreachStore)


def test_campaign_roundtrip_lossless(store):
    c = Campaign(name="Pilot", industry="Electrical", offer="Audit",
                 state=CampaignState.ACTIVE, daily_send_limit=17, campaign_cost=42.0)
    c.add_step(delay_days=0, subject="s {{company}}", body_template="b {{first_name}}", cta="Book")
    c.add_step(delay_days=3, subject="s2", body_template="b2", ai_personalization=False)
    store.save_campaign(c)

    got = store.get_campaign(c.id)
    assert got is not None
    assert got.name == "Pilot"
    assert got.state is CampaignState.ACTIVE
    assert got.daily_send_limit == 17
    assert got.campaign_cost == 42.0
    assert len(got.steps) == 2
    assert got.steps[0].cta == "Book"
    assert got.steps[1].ai_personalization is False


def test_lead_and_flags_roundtrip(store):
    lead = Lead(first_name="Dana", company="Voltify", email="Dana@Voltify.Example",
                icp_score=88.5, unsubscribed=True)
    store.save_lead(lead)
    got = store.get_lead(lead.id)
    assert got.first_name == "Dana"
    assert got.icp_score == 88.5
    assert got.unsubscribed is True


def test_enqueue_idempotency_enforced_by_db(store):
    item1 = QueueItem(campaign_id="c1", lead_id="l1", step_id="s1",
                      scheduled_at=datetime.now(timezone.utc))
    item2 = QueueItem(campaign_id="c1", lead_id="l1", step_id="s1",  # same logical key
                      scheduled_at=datetime.now(timezone.utc))
    assert store.enqueue(item1) is True
    assert store.enqueue(item2) is False  # UNIQUE(idempotency_key) rejects the dup
    assert store.has_queue_key(item1.idempotency_key) is True
    assert len(store.queue_items()) == 1


def test_event_dedup_enforced_by_db(store):
    ev = EmailEvent(event_type=EventType.EMAIL_DELIVERED, provider_message_id="pm_1")
    dup = EmailEvent(event_type=EventType.EMAIL_DELIVERED, provider_message_id="pm_1")
    assert store.record_event(ev) is True
    assert store.record_event(dup) is False
    assert len(store.events()) == 1


def test_sends_on_counts_by_day_and_campaign(store):
    day = "2026-08-12"
    for i, camp in enumerate(["cA", "cA", "cB"]):
        item = QueueItem(campaign_id=camp, lead_id=f"l{i}", step_id="s",
                         scheduled_at=datetime.now(timezone.utc),
                         status=QueueStatus.SENT,
                         completed_at=datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc))
        store.enqueue(item)
        store.save_queue_item(item)
    assert store.sends_on(day) == 3
    assert store.sends_on(day, "cA") == 2
    assert store.sends_on("2026-08-13") == 0


def test_message_by_provider_id(store):
    m = EmailMessage(campaign_id="c", lead_id="l", step_id="s", to_email="a@b.example",
                     subject="hi", body="b", provider_message_id="pm_9")
    store.save_message(m)
    assert store.message_by_provider_id("pm_9").id == m.id
    assert store.message_by_provider_id("nope") is None


def test_suppression_normalized(store):
    store.add_suppression(SuppressionEntry(email="Foo@Bar.Example", reason=SuppressionReason.BOUNCED))
    assert store.is_suppressed("foo@bar.example") is True
    assert store.is_suppressed("FOO@BAR.EXAMPLE") is True
    assert len(store.suppression_entries()) == 1


def test_campaign_lead_upsert_updates(store):
    cl = CampaignLead(campaign_id="c", lead_id="l")
    store.save_campaign_lead(cl)
    cl.state = LeadCampaignState.SENT
    cl.current_step = 2
    store.save_campaign_lead(cl)
    got = store.get_campaign_lead("c", "l")
    assert got.state is LeadCampaignState.SENT
    assert got.current_step == 2
    assert len(store.campaign_leads("c")) == 1


def test_durability_across_reconnect(tmp_path):
    """The core promise: state survives a process/connection restart."""
    db = str(tmp_path / "outreach.db")
    s1 = SqliteOutreachStore(db)
    c = Campaign(name="Persist", state=CampaignState.ACTIVE)
    c.add_step(delay_days=0, subject="s", body_template="b")
    s1.save_campaign(c)
    item = QueueItem(campaign_id=c.id, lead_id="l1", step_id=c.steps[0].id,
                     scheduled_at=datetime.now(timezone.utc))
    s1.enqueue(item)
    s1.close()  # simulate the process dying

    # Fresh store, same file — nothing lost.
    s2 = SqliteOutreachStore(db)
    assert s2.get_campaign(c.id) is not None
    assert len(s2.queue_items(QueueStatus.PENDING)) == 1
    # And the duplicate guard is still enforced after restart.
    assert s2.enqueue(item) is False


def test_full_pipeline_on_sql_store_is_drop_in(config, campaign, lead):
    """The engine/worker/webhooks run unchanged on the SQL store."""
    system = OutreachSystem(config, store=SqliteOutreachStore(":memory:"))
    system.engine.create_campaign(campaign)
    system.engine.add_lead(campaign, lead)
    system.engine.activate(campaign)
    system.engine.enqueue_due(campaign, now=IN_WINDOW)
    result = system.worker.process_once(now=IN_WINDOW)
    assert result.sent == 1

    # webhook -> delivered transition persists
    msg = system.store.message_by_provider_id(
        system.store.queue_items(QueueStatus.SENT)[0].provider_message_id
    )
    from aion_revenue_factory.outreach.providers.base import NormalizedEvent

    system.webhooks.apply(NormalizedEvent(EventType.EMAIL_DELIVERED,
                                          provider_message_id=msg.provider_message_id))
    cl = system.store.get_campaign_lead(campaign.id, lead.id)
    assert cl.state is LeadCampaignState.DELIVERED

    # metrics read back from SQL
    m = system.dashboard.campaign_metrics(campaign)
    assert m["emails_sent"] == 1
    assert m["delivered"] == 1


def test_postgres_placeholder_translation():
    """Postgres path rewrites '?' to '%s' (parity check without a live DB)."""
    conn = sqlite3.connect(":memory:")
    # Force POSTGRES dialect over a sqlite connection would break execution, so
    # only assert the query translation is applied by the dialect.
    store = SqlOutreachStore(conn, POSTGRES.__class__(placeholder="%s"), ensure_schema=False)
    assert store._q("SELECT 1 WHERE id=?") == "SELECT 1 WHERE id=%s"
    conn.close()


def test_wiring_selects_sqlite(monkeypatch, tmp_path):
    db = str(tmp_path / "w.db")
    store = _build_operational_store({"DATABASE_URL": f"sqlite:///{db}"})
    assert isinstance(store, SqliteOutreachStore)
    store.close()


def test_wiring_memory_when_unset():
    assert _build_operational_store({}) is None


def test_describe_wiring_reports_store():
    d = describe_outreach_wiring({"DATABASE_URL": "postgresql://x"})
    assert "postgres" in d["operational_store"]
    d2 = describe_outreach_wiring({})
    assert "in_memory" in d2["operational_store"]
