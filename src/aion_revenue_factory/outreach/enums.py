"""Enumerations for the Outreach Engine.

Kept separate from the core ``domain.enums`` because these describe the
campaign/queue/event lifecycle, which is specific to outreach and should not
bloat the shared revenue-pipeline vocabulary.
"""

from __future__ import annotations

from enum import Enum


class CampaignState(str, Enum):
    """Lifecycle of a whole campaign."""

    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"

    def is_sendable(self) -> bool:
        """Only ACTIVE campaigns may enqueue or send."""
        return self is CampaignState.ACTIVE


class LeadCampaignState(str, Enum):
    """A single lead's state *within* a campaign."""

    QUEUED = "queued"
    SCHEDULED = "scheduled"
    SENDING = "sending"
    SENT = "sent"
    DELIVERED = "delivered"
    REPLIED = "replied"
    BOUNCED = "bounced"
    UNSUBSCRIBED = "unsubscribed"
    MEETING_BOOKED = "meeting_booked"
    CONVERTED = "converted"
    STOPPED = "stopped"

    def is_stopped(self) -> bool:
        """Terminal states that permanently remove a lead from a sequence."""
        return self in _STOPPED_STATES


_STOPPED_STATES = frozenset(
    {
        LeadCampaignState.REPLIED,
        LeadCampaignState.BOUNCED,
        LeadCampaignState.UNSUBSCRIBED,
        LeadCampaignState.MEETING_BOOKED,
        LeadCampaignState.CONVERTED,
        LeadCampaignState.STOPPED,
    }
)


class QueueStatus(str, Enum):
    """Send-queue item lifecycle."""

    PENDING = "pending"
    PROCESSING = "processing"
    SENT = "sent"
    FAILED = "failed"
    CANCELLED = "cancelled"

    def is_terminal(self) -> bool:
        return self in (QueueStatus.SENT, QueueStatus.FAILED, QueueStatus.CANCELLED)


class EventType(str, Enum):
    """Internal, provider-agnostic email events.

    Provider-specific webhook payloads are normalized into exactly these.
    """

    EMAIL_QUEUED = "email_queued"
    EMAIL_SENT = "email_sent"
    EMAIL_DELIVERED = "email_delivered"
    EMAIL_BOUNCED = "email_bounced"
    EMAIL_COMPLAINT = "email_complaint"
    EMAIL_FAILED = "email_failed"
    EMAIL_OPENED = "email_opened"
    EMAIL_CLICKED = "email_clicked"
    EMAIL_UNSUBSCRIBED = "email_unsubscribed"
    LEAD_REPLIED = "lead_replied"


class SuppressionReason(str, Enum):
    """Why an email address is on the global suppression list."""

    UNSUBSCRIBED = "unsubscribed"
    BOUNCED = "bounced"
    COMPLAINT = "complaint"
    DO_NOT_CONTACT = "do_not_contact"
    MANUAL = "manual"
