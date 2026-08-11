from aion_revenue_factory.outreach import (
    CampaignState,
    InMemoryOutreachStore,
    SuppressionReason,
    SuppressionService,
    is_lead_eligible_for_send,
    valid_email,
)


def _prep(store, campaign, lead, active=True):
    campaign.state = CampaignState.ACTIVE if active else CampaignState.DRAFT
    store.save_campaign(campaign)
    store.save_lead(lead)
    return campaign.steps[0]


def test_valid_email():
    assert valid_email("a@b.com")
    assert not valid_email("nope")
    assert not valid_email("")


def test_eligible_happy_path(campaign, lead):
    store = InMemoryOutreachStore()
    step = _prep(store, campaign, lead)
    assert is_lead_eligible_for_send(lead, campaign, step, store).eligible


def test_stop_conditions(campaign, lead):
    store = InMemoryOutreachStore()
    step = _prep(store, campaign, lead)

    for attr, reason in [
        ("unsubscribed", "unsubscribed"),
        ("bounced", "bounced"),
        ("do_not_contact", "do_not_contact"),
        ("has_replied", "replied"),
        ("meeting_booked", "meeting_booked"),
        ("is_customer", "converted"),
    ]:
        setattr(lead, attr, True)
        result = is_lead_eligible_for_send(lead, campaign, step, store)
        assert not result.eligible and result.reason == reason
        setattr(lead, attr, False)


def test_suppressed_blocks(campaign, lead):
    store = InMemoryOutreachStore()
    step = _prep(store, campaign, lead)
    SuppressionService(store).add(lead.email, SuppressionReason.MANUAL)
    result = is_lead_eligible_for_send(lead, campaign, step, store)
    assert not result.eligible and result.reason == "suppressed"


def test_inactive_campaign_blocks(campaign, lead):
    store = InMemoryOutreachStore()
    step = _prep(store, campaign, lead, active=False)
    result = is_lead_eligible_for_send(lead, campaign, step, store)
    assert not result.eligible and result.reason.startswith("campaign_")


def test_invalid_email_blocks(campaign, lead):
    store = InMemoryOutreachStore()
    lead.email = "broken"
    step = _prep(store, campaign, lead)
    result = is_lead_eligible_for_send(lead, campaign, step, store)
    assert not result.eligible and result.reason == "invalid_email"


def test_no_step_blocks(campaign, lead):
    store = InMemoryOutreachStore()
    _prep(store, campaign, lead)
    result = is_lead_eligible_for_send(lead, campaign, None, store)
    assert not result.eligible and result.reason == "no_step_available"


def test_duplicate_send_blocks(campaign, lead):
    from datetime import datetime, timezone

    from aion_revenue_factory.outreach import QueueItem

    store = InMemoryOutreachStore()
    step = _prep(store, campaign, lead)
    store.enqueue(
        QueueItem(campaign_id=campaign.id, lead_id=lead.id, step_id=step.id,
                  scheduled_at=datetime.now(timezone.utc))
    )
    result = is_lead_eligible_for_send(lead, campaign, step, store)
    assert not result.eligible and result.reason == "duplicate_send"
