"""Dataclasses for the Outreach Engine.

These describe the campaign, lead, queue, message, and event entities. IDs use
the same ``prefix_hex`` convention as the core domain so everything reads
consistently in the CRM.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .enums import (
    CampaignState,
    EventType,
    LeadCampaignState,
    QueueStatus,
    SuppressionReason,
)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


@dataclass
class Lead:
    """A qualified lead pulled from Airtable, with campaign-safety fields.

    This is distinct from the core ``Opportunity`` (a discovery-side entity):
    a Lead carries the compliance/lifecycle flags the engine's stop conditions
    read (unsubscribed, bounced, do-not-contact, reply/meeting/customer status).
    """

    email: str
    first_name: str = ""
    last_name: str = ""
    company: str = ""
    job_title: str = ""
    industry: str = ""
    location: str = ""
    website: str = ""
    phone: str = ""
    lead_source: str = ""
    icp_score: float = 0.0
    owner: str = ""
    notes: str = ""
    # Airtable record id, when synced from a live base (for write-back).
    airtable_id: str = ""

    # Compliance / lifecycle flags — read by the canonical eligibility check.
    unsubscribed: bool = False
    bounced: bool = False
    do_not_contact: bool = False
    has_replied: bool = False
    meeting_booked: bool = False
    is_customer: bool = False

    id: str = field(default_factory=lambda: _new_id("lead"))

    @property
    def full_name(self) -> str:
        name = f"{self.first_name} {self.last_name}".strip()
        return name or self.email

    def stop_reason(self) -> Optional[str]:
        """Human-readable reason this lead is off-limits, or None if reachable.

        Purely descriptive — the authoritative gate is
        :func:`outreach.eligibility.is_lead_eligible_for_send`.
        """
        if self.unsubscribed:
            return "unsubscribed"
        if self.bounced:
            return "bounced"
        if self.do_not_contact:
            return "do_not_contact"
        if self.has_replied:
            return "replied"
        if self.meeting_booked:
            return "meeting_booked"
        if self.is_customer:
            return "converted"
        return None


@dataclass
class CampaignStep:
    """One step of a multi-step sequence."""

    campaign_id: str
    order: int  # 1-based position in the sequence
    delay_days: int  # days after the *previous* step (step 1 is day 0)
    subject: str
    body_template: str
    cta: str = ""
    ai_personalization: bool = True
    active: bool = True
    id: str = field(default_factory=lambda: _new_id("step"))


@dataclass
class Campaign:
    """A campaign: an audience + a sequence + sending policy."""

    name: str
    description: str = ""
    icp: str = ""
    industry: str = ""
    offer: str = ""
    state: CampaignState = CampaignState.DRAFT
    daily_send_limit: int = 50
    steps: list[CampaignStep] = field(default_factory=list)
    start_date: Optional[str] = None  # ISO date string
    end_date: Optional[str] = None
    campaign_cost: float = 0.0  # externally-tracked fixed cost (tools, lists…)
    id: str = field(default_factory=lambda: _new_id("camp"))
    created_at: datetime = field(default_factory=datetime.utcnow)

    def add_step(
        self,
        *,
        delay_days: int,
        subject: str,
        body_template: str,
        cta: str = "",
        ai_personalization: bool = True,
    ) -> CampaignStep:
        step = CampaignStep(
            campaign_id=self.id,
            order=len(self.steps) + 1,
            delay_days=delay_days,
            subject=subject,
            body_template=body_template,
            cta=cta,
            ai_personalization=ai_personalization,
        )
        self.steps.append(step)
        return step

    def active_steps(self) -> list[CampaignStep]:
        return [s for s in self.steps if s.active]

    def step_by_order(self, order: int) -> Optional[CampaignStep]:
        for s in self.steps:
            if s.order == order:
                return s
        return None


@dataclass
class CampaignLead:
    """The association of a lead to a campaign, with per-campaign progress."""

    campaign_id: str
    lead_id: str
    state: LeadCampaignState = LeadCampaignState.QUEUED
    current_step: int = 0  # highest step order sent so far (0 = none yet)
    last_sent_at: Optional[datetime] = None
    next_step_at: Optional[datetime] = None
    stopped_reason: str = ""
    # Revenue-attribution signals set as a lead progresses.
    positive_reply: bool = False
    opportunity: bool = False
    revenue: float = 0.0
    id: str = field(default_factory=lambda: _new_id("clead"))


@dataclass
class EmailMessage:
    """A concrete email produced for a (lead, campaign, step)."""

    campaign_id: str
    lead_id: str
    step_id: str
    to_email: str
    subject: str
    body: str
    from_email: str = ""
    reply_to: str = ""
    provider: str = ""
    provider_message_id: str = ""
    status: str = "created"
    # For test-mode redirection: the real recipient is preserved here.
    intended_recipient: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)
    sent_at: Optional[datetime] = None
    id: str = field(default_factory=lambda: _new_id("email"))


@dataclass
class EmailEvent:
    """A normalized, provider-agnostic email event."""

    event_type: EventType
    lead_id: str = ""
    campaign_id: str = ""
    email_id: str = ""
    provider_message_id: str = ""
    provider: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: _new_id("evt"))

    @property
    def dedupe_key(self) -> str:
        """Idempotency key: same provider message + same type = same event."""
        return f"{self.provider_message_id}:{self.event_type.value}"


@dataclass
class QueueItem:
    """A scheduled send. The unit the worker processes."""

    campaign_id: str
    lead_id: str
    step_id: str
    scheduled_at: datetime
    status: QueueStatus = QueueStatus.PENDING
    attempts: int = 0
    last_attempt_at: Optional[datetime] = None
    provider: str = ""
    provider_message_id: str = ""
    error: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    id: str = field(default_factory=lambda: _new_id("q"))

    @property
    def idempotency_key(self) -> str:
        """The logical key that must never be enqueued twice."""
        return f"{self.lead_id}:{self.campaign_id}:{self.step_id}"


@dataclass
class SuppressionEntry:
    """An address that must never be contacted again."""

    email: str
    reason: SuppressionReason
    note: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)
    id: str = field(default_factory=lambda: _new_id("supp"))


@dataclass
class AIGeneration:
    """An audit record of one AI personalization call."""

    lead_id: str
    campaign_id: str
    step_id: str
    subject: str
    body: str
    rationale: str
    confidence: float
    model: str = ""
    prompt: str = ""
    estimated_cost: float = 0.0
    created_at: datetime = field(default_factory=datetime.utcnow)
    id: str = field(default_factory=lambda: _new_id("gen"))
