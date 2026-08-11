"""Multi-worker claiming: atomic claims, no double-send, stale reclaim.

Exercised against both the in-memory store and the SQL (sqlite) store — the
sqlite path runs the same BEGIN IMMEDIATE + conditional-UPDATE claim that the
Postgres path runs with FOR UPDATE SKIP LOCKED.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

import pytest

from aion_revenue_factory.outreach import (
    Campaign,
    CampaignState,
    InMemoryOutreachStore,
    Lead,
    OutreachConfig,
    OutreachSystem,
    QueueItem,
    QueueStatus,
    SqliteOutreachStore,
)

from .conftest import IN_WINDOW

NOW = datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)


def _mk_items(store, n, *, scheduled=NOW):
    for i in range(n):
        store.enqueue(QueueItem(campaign_id="c", lead_id=f"l{i}", step_id="s1",
                                scheduled_at=scheduled))


@pytest.fixture(params=["memory", "sqlite"])
def store(request):
    return InMemoryOutreachStore() if request.param == "memory" else SqliteOutreachStore(":memory:")


def test_claim_marks_processing_and_returns(store):
    _mk_items(store, 3)
    claimed = store.claim_due(NOW, 10, "w1")
    assert len(claimed) == 3
    assert all(c.status is QueueStatus.PROCESSING for c in claimed)
    assert all(c.claimed_by == "w1" for c in claimed)
    # persisted
    assert len(store.queue_items(QueueStatus.PROCESSING)) == 3
    assert len(store.queue_items(QueueStatus.PENDING)) == 0


def test_second_claim_gets_nothing_once_all_claimed(store):
    _mk_items(store, 2)
    first = store.claim_due(NOW, 10, "w1")
    second = store.claim_due(NOW, 10, "w2")
    assert len(first) == 2
    assert second == []  # already claimed -> not re-claimed


def test_claim_respects_limit_and_schedule(store):
    _mk_items(store, 5)
    # one item scheduled in the future must not be claimed now
    store.enqueue(QueueItem(campaign_id="c", lead_id="future", step_id="s1",
                            scheduled_at=NOW + timedelta(days=2)))
    claimed = store.claim_due(NOW, 3, "w1")
    assert len(claimed) == 3
    assert all(c.lead_id != "future" for c in claimed)


def test_disjoint_claims_two_workers(store):
    _mk_items(store, 6)
    a = store.claim_due(NOW, 3, "wA")
    b = store.claim_due(NOW, 3, "wB")
    ids_a = {i.id for i in a}
    ids_b = {i.id for i in b}
    assert len(ids_a) == 3 and len(ids_b) == 3
    assert ids_a.isdisjoint(ids_b)  # no item claimed by both


def test_reclaim_stale_returns_to_pending(store):
    _mk_items(store, 2)
    store.claim_due(NOW, 10, "dead_worker")
    assert len(store.queue_items(QueueStatus.PROCESSING)) == 2
    # Nothing stale yet (just claimed).
    assert store.reclaim_stale(NOW, older_than_seconds=900) == 0
    # 20 minutes later, the dead worker's claims are reclaimed.
    later = NOW + timedelta(minutes=20)
    assert store.reclaim_stale(later, older_than_seconds=900) == 2
    assert len(store.queue_items(QueueStatus.PENDING)) == 2
    assert len(store.queue_items(QueueStatus.PROCESSING)) == 0


def test_two_stores_same_file_no_double_claim(tmp_path):
    """Two store instances (simulating two worker processes) on one sqlite file
    never hand the same item to both."""
    db = str(tmp_path / "claims.db")
    writer = SqliteOutreachStore(db)
    _mk_items(writer, 8)

    w1 = SqliteOutreachStore(db)
    w2 = SqliteOutreachStore(db)
    c1 = w1.claim_due(NOW, 5, "w1")
    c2 = w2.claim_due(NOW, 5, "w2")
    ids = {i.id for i in c1} | {i.id for i in c2}
    assert len(c1) + len(c2) == 8      # all claimed exactly once
    assert len(ids) == 8               # no overlap
    for s in (writer, w1, w2):
        s.close()


def test_concurrent_threads_no_double_claim(tmp_path):
    db = str(tmp_path / "threads.db")
    writer = SqliteOutreachStore(db)
    _mk_items(writer, 20)
    writer.close()

    results: list[list[str]] = []
    barrier = threading.Barrier(4)

    def worker(name):
        s = SqliteOutreachStore(db)
        barrier.wait()  # maximize contention
        got = [i.id for i in s.claim_due(NOW, 20, name)]
        results.append(got)
        s.close()

    threads = [threading.Thread(target=worker, args=(f"w{i}",)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    all_ids = [i for r in results for i in r]
    assert len(all_ids) == 20            # every item claimed
    assert len(set(all_ids)) == 20       # each exactly once (no double-claim)


def test_worker_reclaims_and_sends_after_crash(config, campaign, lead):
    """An item a dead worker claimed but never sent is reclaimed and delivered
    on a later cycle — no message is lost."""
    config.claim_stale_seconds = 600
    system = OutreachSystem(config, store=SqliteOutreachStore(":memory:"))
    system.engine.create_campaign(campaign)
    system.engine.add_lead(campaign, lead)
    system.engine.activate(campaign)
    system.engine.enqueue_due(campaign, now=IN_WINDOW)

    # Simulate a worker that claimed the item and then died (never processed it).
    system.store.claim_due(IN_WINDOW, 10, "dead_worker")
    assert len(system.store.queue_items(QueueStatus.PROCESSING)) == 1

    # A healthy worker runs 20 minutes later: reclaim kicks in, then it sends.
    later = IN_WINDOW + timedelta(minutes=20)
    result = system.worker.process_once(now=later)
    assert result.sent == 1
    assert len(system.store.queue_items(QueueStatus.SENT)) == 1
    assert len(system.store.queue_items(QueueStatus.PROCESSING)) == 0


def test_worker_defers_over_campaign_limit_via_release(config, lead):
    """Per-campaign daily limit: claimed-but-over-limit items are released back
    to PENDING (deferred), not sent."""
    config.max_daily_sends = 100
    system = OutreachSystem(config, store=SqliteOutreachStore(":memory:"))
    campaign = Campaign(name="capped", industry="X", offer="O",
                        state=CampaignState.DRAFT, daily_send_limit=2)
    campaign.add_step(delay_days=0, subject="s {{company}}", body_template="b {{first_name}}")
    system.engine.create_campaign(campaign)
    leads = [Lead(first_name=f"L{i}", company=f"C{i}", email=f"l{i}@ex.example", icp_score=80)
             for i in range(5)]
    system.engine.add_leads(campaign, leads)
    system.engine.activate(campaign)
    system.engine.enqueue_due(campaign, now=IN_WINDOW)

    result = system.worker.process_once(now=IN_WINDOW)
    assert result.sent == 2                      # campaign daily limit honored
    assert result.reasons.get("campaign_daily_limit", 0) >= 1
    # deferred items are back to PENDING, not stuck in PROCESSING
    assert len(system.store.queue_items(QueueStatus.PROCESSING)) == 0
    assert len(system.store.queue_items(QueueStatus.PENDING)) == 3
