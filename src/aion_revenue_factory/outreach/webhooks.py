"""Webhook event processing.

Turns raw provider webhooks into internal state transitions, safely:

1. The provider verifies the signature and normalizes payloads into
   ``NormalizedEvent`` (unknown/forged payloads never reach here as events).
2. Processing is **idempotent**: an event is keyed by
   ``provider_message_id + event_type``; a replay is ignored, so no duplicate
   state transitions.
3. Bounces and complaints add the address to the global suppression list and
   stop the lead's sequence.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .enums import EventType, LeadCampaignState, SuppressionReason
from .logging import log_event
from .models import EmailEvent
from .providers.base import EmailProvider, NormalizedEvent
from .store import OutreachStore
from .suppression import SuppressionService

# Which internal events suppress the address (and why).
_SUPPRESS_ON = {
    EventType.EMAIL_BOUNCED: SuppressionReason.BOUNCED,
    EventType.EMAIL_COMPLAINT: SuppressionReason.COMPLAINT,
    EventType.EMAIL_UNSUBSCRIBED: SuppressionReason.UNSUBSCRIBED,
}

# Internal event -> resulting lead-campaign state (when we can resolve the lead).
_LEAD_STATE = {
    EventType.EMAIL_DELIVERED: LeadCampaignState.DELIVERED,
    EventType.EMAIL_BOUNCED: LeadCampaignState.BOUNCED,
    EventType.EMAIL_COMPLAINT: LeadCampaignState.UNSUBSCRIBED,
    EventType.EMAIL_UNSUBSCRIBED: LeadCampaignState.UNSUBSCRIBED,
    EventType.LEAD_REPLIED: LeadCampaignState.REPLIED,
}


class WebhookProcessor:
    def __init__(self, store: OutreachStore, provider: EmailProvider) -> None:
        self.store = store
        self.provider = provider
        self.suppression = SuppressionService(store)

    def handle(self, headers: dict, body: bytes) -> list[EmailEvent]:
        """Verify + normalize + apply a raw webhook. Returns applied events."""
        normalized = self.provider.parse_webhook(headers, body)
        applied: list[EmailEvent] = []
        for ev in normalized:
            result = self.apply(ev)
            if result is not None:
                applied.append(result)
        return applied

    def apply(self, ev: NormalizedEvent) -> EmailEvent | None:
        """Apply one normalized event idempotently. Returns None if a duplicate."""
        message = self.store.message_by_provider_id(ev.provider_message_id)
        lead_id = message.lead_id if message else ""
        campaign_id = message.campaign_id if message else ""
        email_addr = ev.email or (message.intended_recipient or message.to_email if message else "")

        event = EmailEvent(
            event_type=ev.event_type,
            lead_id=lead_id,
            campaign_id=campaign_id,
            email_id=message.id if message else "",
            provider_message_id=ev.provider_message_id,
            provider=getattr(self.provider, "name", ""),
            timestamp=ev.timestamp or datetime.now(timezone.utc),
            metadata=ev.metadata,
        )

        # Idempotency: identical (provider_message_id, event_type) is ignored.
        if not self.store.record_event(event):
            log_event("email.event_duplicate", provider_message_id=ev.provider_message_id,
                      event_type=ev.event_type.value)
            return None

        # Suppress on bounce / complaint / unsubscribe.
        reason = _SUPPRESS_ON.get(ev.event_type)
        if reason is not None and email_addr:
            self.suppression.add(email_addr, reason, note=f"via webhook {ev.event_type.value}")
            lead = self.store.get_lead(lead_id) if lead_id else None
            if lead is not None:
                if reason is SuppressionReason.BOUNCED:
                    lead.bounced = True
                else:
                    lead.unsubscribed = True
                self.store.save_lead(lead)
            log_event("lead.suppressed", lead_id=lead_id, campaign_id=campaign_id,
                      reason=reason.value, event_type=ev.event_type.value)

        # Advance the lead's campaign state where meaningful.
        new_state = _LEAD_STATE.get(ev.event_type)
        if new_state is not None and campaign_id and lead_id:
            cl = self.store.get_campaign_lead(campaign_id, lead_id)
            if cl is not None:
                # Don't regress a stopped lead back to DELIVERED.
                if not (cl.state.is_stopped() and new_state is LeadCampaignState.DELIVERED):
                    cl.state = new_state
                    if new_state.is_stopped():
                        cl.stopped_reason = ev.event_type.value
                    self.store.save_campaign_lead(cl)

        log_event("email.event", lead_id=lead_id, campaign_id=campaign_id,
                  provider=event.provider, event_type=ev.event_type.value,
                  provider_message_id=ev.provider_message_id)
        return event
