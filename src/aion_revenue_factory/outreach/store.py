"""Operational state store for the Outreach Engine.

Airtable stays the CRM / source-of-truth for lead & revenue relationships, but
high-volume operational state — the send queue, email events, suppression list,
per-campaign lead progress — is better kept in a fast operational store. This is
the same Protocol + in-memory-reference pattern the core ``CRM`` uses.

The in-memory store enforces the two uniqueness rules the engine depends on:

- one queue item per ``lead_id + campaign_id + step_id`` (no duplicate sends),
- one processed event per ``provider_message_id + event_type`` (idempotency).
"""

from __future__ import annotations

from typing import Iterable, Optional, Protocol, runtime_checkable

from .enums import QueueStatus
from .models import (
    AIGeneration,
    Campaign,
    CampaignLead,
    EmailEvent,
    EmailMessage,
    Lead,
    QueueItem,
    SuppressionEntry,
)


@runtime_checkable
class OutreachStore(Protocol):
    # campaigns
    def save_campaign(self, campaign: Campaign) -> None: ...
    def get_campaign(self, campaign_id: str) -> Optional[Campaign]: ...
    def campaigns(self) -> Iterable[Campaign]: ...
    # leads
    def save_lead(self, lead: Lead) -> None: ...
    def get_lead(self, lead_id: str) -> Optional[Lead]: ...
    def leads(self) -> Iterable[Lead]: ...
    # campaign membership
    def save_campaign_lead(self, cl: CampaignLead) -> None: ...
    def campaign_leads(self, campaign_id: str) -> list[CampaignLead]: ...
    def get_campaign_lead(self, campaign_id: str, lead_id: str) -> Optional[CampaignLead]: ...
    # queue
    def enqueue(self, item: QueueItem) -> bool: ...
    def has_queue_key(self, idempotency_key: str) -> bool: ...
    def queue_items(self, status: Optional[QueueStatus] = None) -> list[QueueItem]: ...
    def save_queue_item(self, item: QueueItem) -> None: ...
    def sends_on(self, day_iso: str, campaign_id: Optional[str] = None) -> int: ...
    # messages / events / generations
    def save_message(self, message: EmailMessage) -> None: ...
    def get_message(self, message_id: str) -> Optional[EmailMessage]: ...
    def message_by_provider_id(self, provider_message_id: str) -> Optional[EmailMessage]: ...
    def record_event(self, event: EmailEvent) -> bool: ...
    def events(self) -> list[EmailEvent]: ...
    def save_generation(self, generation: AIGeneration) -> None: ...
    # suppression
    def add_suppression(self, entry: SuppressionEntry) -> None: ...
    def is_suppressed(self, email: str) -> bool: ...
    def suppression_entries(self) -> list[SuppressionEntry]: ...


class InMemoryOutreachStore:
    """Inspectable reference store. Good enough for tests and offline runs."""

    def __init__(self) -> None:
        self._campaigns: dict[str, Campaign] = {}
        self._leads: dict[str, Lead] = {}
        self._campaign_leads: dict[str, CampaignLead] = {}
        self._queue: dict[str, QueueItem] = {}
        self._queue_keys: set[str] = set()
        self._messages: dict[str, EmailMessage] = {}
        self._events: list[EmailEvent] = []
        self._event_keys: set[str] = set()
        self._generations: list[AIGeneration] = []
        self._suppressed: dict[str, SuppressionEntry] = {}

    # ---- campaigns ----
    def save_campaign(self, campaign: Campaign) -> None:
        self._campaigns[campaign.id] = campaign

    def get_campaign(self, campaign_id: str) -> Optional[Campaign]:
        return self._campaigns.get(campaign_id)

    def campaigns(self) -> list[Campaign]:
        return list(self._campaigns.values())

    # ---- leads ----
    def save_lead(self, lead: Lead) -> None:
        self._leads[lead.id] = lead

    def get_lead(self, lead_id: str) -> Optional[Lead]:
        return self._leads.get(lead_id)

    def leads(self) -> list[Lead]:
        return list(self._leads.values())

    # ---- campaign membership ----
    @staticmethod
    def _cl_key(campaign_id: str, lead_id: str) -> str:
        return f"{campaign_id}:{lead_id}"

    def save_campaign_lead(self, cl: CampaignLead) -> None:
        self._campaign_leads[self._cl_key(cl.campaign_id, cl.lead_id)] = cl

    def campaign_leads(self, campaign_id: str) -> list[CampaignLead]:
        return [c for c in self._campaign_leads.values() if c.campaign_id == campaign_id]

    def get_campaign_lead(self, campaign_id: str, lead_id: str) -> Optional[CampaignLead]:
        return self._campaign_leads.get(self._cl_key(campaign_id, lead_id))

    # ---- queue ----
    def enqueue(self, item: QueueItem) -> bool:
        """Insert a queue item unless its idempotency key already exists.

        Returns True if inserted, False if it was a duplicate (already queued).
        """
        if item.idempotency_key in self._queue_keys:
            return False
        self._queue_keys.add(item.idempotency_key)
        self._queue[item.id] = item
        return True

    def has_queue_key(self, idempotency_key: str) -> bool:
        return idempotency_key in self._queue_keys

    def queue_items(self, status: Optional[QueueStatus] = None) -> list[QueueItem]:
        items = list(self._queue.values())
        if status is not None:
            items = [i for i in items if i.status is status]
        return items

    def save_queue_item(self, item: QueueItem) -> None:
        self._queue[item.id] = item

    def sends_on(self, day_iso: str, campaign_id: Optional[str] = None) -> int:
        """Count queue items marked SENT whose completion day == ``day_iso``."""
        count = 0
        for item in self._queue.values():
            if item.status is not QueueStatus.SENT or item.completed_at is None:
                continue
            if item.completed_at.date().isoformat() != day_iso:
                continue
            if campaign_id is not None and item.campaign_id != campaign_id:
                continue
            count += 1
        return count

    # ---- messages / events / generations ----
    def save_message(self, message: EmailMessage) -> None:
        self._messages[message.id] = message

    def get_message(self, message_id: str) -> Optional[EmailMessage]:
        return self._messages.get(message_id)

    def message_by_provider_id(self, provider_message_id: str) -> Optional[EmailMessage]:
        if not provider_message_id:
            return None
        for m in self._messages.values():
            if m.provider_message_id == provider_message_id:
                return m
        return None

    def record_event(self, event: EmailEvent) -> bool:
        """Record an event unless an identical one was already processed.

        Returns True if newly recorded, False if it was a duplicate.
        """
        if event.dedupe_key in self._event_keys:
            return False
        self._event_keys.add(event.dedupe_key)
        self._events.append(event)
        return True

    def events(self) -> list[EmailEvent]:
        return list(self._events)

    def save_generation(self, generation: AIGeneration) -> None:
        self._generations.append(generation)

    def generations(self) -> list[AIGeneration]:
        return list(self._generations)

    # ---- suppression ----
    @staticmethod
    def _norm(email: str) -> str:
        return email.strip().lower()

    def add_suppression(self, entry: SuppressionEntry) -> None:
        self._suppressed[self._norm(entry.email)] = entry

    def is_suppressed(self, email: str) -> bool:
        return self._norm(email) in self._suppressed

    def suppression_entries(self) -> list[SuppressionEntry]:
        return list(self._suppressed.values())
