from datetime import datetime, timezone

from aion_revenue_factory.outreach import (
    EventType,
    LeadCampaignState,
)
from aion_revenue_factory.outreach.providers.base import NormalizedEvent

from .conftest import IN_WINDOW


def _send_one(system, campaign, lead):
    system.engine.create_campaign(campaign)
    system.engine.add_lead(campaign, lead)
    system.engine.activate(campaign)
    system.engine.enqueue_due(campaign, now=IN_WINDOW)
    system.worker.process_once(now=IN_WINDOW)
    # The console provider id is stored on the message.
    msgs = [m for m in system.store._messages.values()]  # noqa: SLF001 (test introspection)
    return msgs[0]


def test_delivered_event_updates_state(system, campaign, lead):
    msg = _send_one(system, campaign, lead)
    ev = NormalizedEvent(EventType.EMAIL_DELIVERED, provider_message_id=msg.provider_message_id)
    applied = system.webhooks.apply(ev)
    assert applied is not None
    cl = system.store.get_campaign_lead(campaign.id, lead.id)
    assert cl.state is LeadCampaignState.DELIVERED


def test_bounce_suppresses_and_stops(system, campaign, lead):
    msg = _send_one(system, campaign, lead)
    ev = NormalizedEvent(EventType.EMAIL_BOUNCED, provider_message_id=msg.provider_message_id,
                         email=lead.email)
    system.webhooks.apply(ev)
    assert system.store.is_suppressed(lead.email)
    assert system.store.get_lead(lead.id).bounced is True
    cl = system.store.get_campaign_lead(campaign.id, lead.id)
    assert cl.state is LeadCampaignState.BOUNCED


def test_complaint_suppresses(system, campaign, lead):
    msg = _send_one(system, campaign, lead)
    ev = NormalizedEvent(EventType.EMAIL_COMPLAINT, provider_message_id=msg.provider_message_id,
                         email=lead.email)
    system.webhooks.apply(ev)
    assert system.store.is_suppressed(lead.email)


def test_idempotent_event_processing(system, campaign, lead):
    msg = _send_one(system, campaign, lead)
    ev = NormalizedEvent(EventType.EMAIL_DELIVERED, provider_message_id=msg.provider_message_id)
    first = system.webhooks.apply(ev)
    second = system.webhooks.apply(ev)  # replay
    assert first is not None
    assert second is None  # duplicate ignored, no double transition
    delivered = [e for e in system.store.events() if e.event_type is EventType.EMAIL_DELIVERED]
    assert len(delivered) == 1


def test_suppressed_lead_not_resent(system, campaign, lead):
    msg = _send_one(system, campaign, lead)
    system.webhooks.apply(
        NormalizedEvent(EventType.EMAIL_BOUNCED, provider_message_id=msg.provider_message_id,
                        email=lead.email)
    )
    # Attempt a later step; the bounced lead must not be enqueued.
    from datetime import timedelta

    created = system.engine.enqueue_due(campaign, now=IN_WINDOW + timedelta(days=3))
    assert created == []
