from datetime import timedelta

from aion_revenue_factory.outreach import (
    CampaignState,
    LeadCampaignState,
    QueueStatus,
)

from .conftest import IN_WINDOW


def _enroll_and_activate(system, campaign, lead):
    system.engine.create_campaign(campaign)
    system.engine.add_lead(campaign, lead)
    system.engine.activate(campaign)


def test_activate_requires_steps(system):
    from aion_revenue_factory.outreach import Campaign

    empty = Campaign(name="empty")
    system.engine.create_campaign(empty)
    try:
        system.engine.activate(empty)
        assert False, "should have raised"
    except ValueError:
        pass


def test_enqueue_and_send(system, campaign, lead):
    _enroll_and_activate(system, campaign, lead)
    created = system.engine.enqueue_due(campaign, now=IN_WINDOW)
    assert len(created) == 1
    result = system.worker.process_once(now=IN_WINDOW)
    assert result.sent == 1
    assert len(system.provider.outbox) == 1
    cl = system.store.get_campaign_lead(campaign.id, lead.id)
    assert cl.state is LeadCampaignState.SENT
    assert cl.current_step == 1


def test_duplicate_enqueue_prevented(system, campaign, lead):
    _enroll_and_activate(system, campaign, lead)
    first = system.engine.enqueue_due(campaign, now=IN_WINDOW)
    second = system.engine.enqueue_due(campaign, now=IN_WINDOW)
    assert len(first) == 1
    assert len(second) == 0  # idempotency key already present


def test_sequence_progression(system, campaign, lead):
    _enroll_and_activate(system, campaign, lead)
    system.engine.enqueue_due(campaign, now=IN_WINDOW)
    system.worker.process_once(now=IN_WINDOW)
    cl = system.store.get_campaign_lead(campaign.id, lead.id)
    assert cl.current_step == 1

    # Next step becomes due ~3 days later; the scheduler snaps a weekend due
    # date into the next Monday window, so process at the item's own scheduled
    # time rather than assuming raw now+3d is inside the window.
    later = IN_WINDOW + timedelta(days=3)
    created = system.engine.enqueue_due(campaign, now=later)
    assert len(created) == 1
    scheduled_at = created[0].scheduled_at
    system.worker.process_once(now=scheduled_at)
    cl = system.store.get_campaign_lead(campaign.id, lead.id)
    assert cl.current_step == 2


def test_pause_cancels_pending(system, campaign, lead):
    _enroll_and_activate(system, campaign, lead)
    system.engine.enqueue_due(campaign, now=IN_WINDOW)
    system.engine.pause(campaign)
    assert campaign.state is CampaignState.PAUSED
    pending = system.store.queue_items(QueueStatus.PENDING)
    assert pending == []
    cancelled = system.store.queue_items(QueueStatus.CANCELLED)
    assert len(cancelled) == 1


def test_paused_campaign_does_not_enqueue(system, campaign, lead):
    _enroll_and_activate(system, campaign, lead)
    system.engine.pause(campaign)
    created = system.engine.enqueue_due(campaign, now=IN_WINDOW)
    assert created == []


def test_resume_reenables(system, campaign, lead):
    _enroll_and_activate(system, campaign, lead)
    system.engine.pause(campaign)
    system.engine.resume(campaign)
    assert campaign.state is CampaignState.ACTIVE
    created = system.engine.enqueue_due(campaign, now=IN_WINDOW)
    assert len(created) == 1


def test_reply_stops_sequence(system, campaign, lead):
    _enroll_and_activate(system, campaign, lead)
    system.engine.enqueue_due(campaign, now=IN_WINDOW)
    system.worker.process_once(now=IN_WINDOW)
    system.engine.mark_reply(campaign.id, lead.id, positive=True)
    cl = system.store.get_campaign_lead(campaign.id, lead.id)
    assert cl.state is LeadCampaignState.REPLIED
    # No further steps enqueue.
    later = IN_WINDOW + timedelta(days=3)
    assert system.engine.enqueue_due(campaign, now=later) == []


def test_global_daily_limit_enforced(config, campaign):
    from aion_revenue_factory.outreach import Lead, OutreachSystem

    config.max_daily_sends = 2
    system = OutreachSystem(config)
    system.engine.create_campaign(campaign)
    leads = [
        Lead(first_name=f"L{i}", company=f"C{i}", email=f"l{i}@ex.example", icp_score=80)
        for i in range(5)
    ]
    system.engine.add_leads(campaign, leads)
    system.engine.activate(campaign)
    system.engine.enqueue_due(campaign, now=IN_WINDOW)
    result = system.worker.process_once(now=IN_WINDOW)
    assert result.sent == 2  # refuses to exceed the global daily limit
    # The rest are never claimed — they wait as PENDING for a later cycle/day.
    assert len(system.store.queue_items(QueueStatus.PENDING)) == 3
    # A second cycle the same day still sends nothing (budget spent).
    assert system.worker.process_once(now=IN_WINDOW).sent == 0


def test_segment_by_icp_and_industry():
    from aion_revenue_factory.outreach import CampaignEngine, Lead

    leads = [
        Lead(email="a@x.example", icp_score=90, industry="Electrical Contracting"),
        Lead(email="b@x.example", icp_score=40, industry="Electrical Contracting"),
        Lead(email="c@x.example", icp_score=95, industry="Plumbing"),
    ]
    out = CampaignEngine.segment(leads, icp_min=60, industries=["Electrical Contracting"])
    assert [l.email for l in out] == ["a@x.example"]
