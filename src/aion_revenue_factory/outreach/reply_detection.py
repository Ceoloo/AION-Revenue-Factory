"""Reply detection — integration boundary (V1: interface + service, PENDING wiring).

Per the spec: design reply detection as an integration boundary and DO NOT fake
it. This module defines the ``InboundEmailProvider`` protocol and a
``ReplyDetectionService`` that applies a *real* detected reply to lead/campaign
state — but no concrete inbound provider is shipped in V1. Wire one (IMAP poll,
Gmail push, provider inbound-parse webhook) and the stop logic already works.

Until an ``InboundEmailProvider`` is injected, ``poll()`` returns nothing and
``pending()`` reports the integration as not yet connected — the system never
invents a reply.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Protocol, runtime_checkable

from .enums import EventType, LeadCampaignState
from .logging import log_event
from .models import EmailEvent
from .store import OutreachStore


@dataclass(frozen=True)
class InboundReply:
    """A detected inbound reply, resolved to a lead where possible."""

    from_email: str
    lead_id: str = ""
    campaign_id: str = ""
    subject: str = ""
    received_at: Optional[datetime] = None
    is_auto_reply: bool = False


@runtime_checkable
class InboundEmailProvider(Protocol):
    """Anything that can surface new inbound replies since the last poll."""

    name: str

    def fetch_replies(self) -> list[InboundReply]: ...


class ReplyDetectionService:
    """Applies detected replies to lead/campaign state and stops the sequence."""

    def __init__(self, store: OutreachStore, provider: Optional[InboundEmailProvider] = None) -> None:
        self.store = store
        self.provider = provider

    def is_connected(self) -> bool:
        return self.provider is not None

    def pending(self) -> dict:
        """Report integration status (used by health checks / dashboard)."""
        return {
            "connected": self.is_connected(),
            "provider": getattr(self.provider, "name", None),
            "status": "connected" if self.is_connected() else "PENDING — no InboundEmailProvider wired",
        }

    def poll(self) -> list[EmailEvent]:
        """Fetch and apply new replies. No-op (returns []) until a provider is wired."""
        if self.provider is None:
            return []
        events: list[EmailEvent] = []
        for reply in self.provider.fetch_replies():
            if reply.is_auto_reply:
                continue  # out-of-office etc. must not count as a real reply
            events.append(self.apply(reply))
        return events

    def apply(self, reply: InboundReply) -> EmailEvent:
        lead = self.store.get_lead(reply.lead_id) if reply.lead_id else None
        if lead is not None:
            lead.has_replied = True
            self.store.save_lead(lead)
        if reply.campaign_id and reply.lead_id:
            cl = self.store.get_campaign_lead(reply.campaign_id, reply.lead_id)
            if cl is not None:
                cl.state = LeadCampaignState.REPLIED
                cl.stopped_reason = "replied"
                self.store.save_campaign_lead(cl)
        event = EmailEvent(
            event_type=EventType.LEAD_REPLIED,
            lead_id=reply.lead_id,
            campaign_id=reply.campaign_id,
            metadata={"from": reply.from_email, "subject": reply.subject},
        )
        self.store.record_event(event)
        log_event("lead.replied", lead_id=reply.lead_id, campaign_id=reply.campaign_id,
                  event_type="lead_replied")
        return event
