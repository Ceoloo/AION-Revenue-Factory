"""Dataclasses describing every entity that flows through the factory."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from .enums import Channel, OfferType, Stage, funnel_index


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


@dataclass
class Scores:
    """The quantitative read Opportunity Discovery attaches to a prospect.

    All 0-100 except ``estimated_contract_value`` which is in dollars.
    """

    revenue_score: float = 0.0
    urgency_score: float = 0.0
    buying_intent: float = 0.0
    contact_confidence: float = 0.0
    estimated_contract_value: float = 0.0

    @property
    def composite(self) -> float:
        """Single ranking number blending the qualitative signals.

        Estimated contract value is folded in on a log-ish scale so a huge
        deal does not automatically dwarf a high-intent smaller one.
        """
        value_factor = min(self.estimated_contract_value / 50_000.0, 2.0)
        return round(
            0.30 * self.revenue_score
            + 0.25 * self.buying_intent
            + 0.20 * self.urgency_score
            + 0.15 * self.contact_confidence
            + 10.0 * value_factor,
            2,
        )


@dataclass
class Contact:
    name: str
    title: str
    email: str
    confidence: float = 0.0  # 0-100, how sure we are the contact is reachable


@dataclass
class Opportunity:
    """A discovered prospect: business, creator, agency, investor, etc."""

    name: str
    industry: str
    kind: str = "business"  # business | creator | agency | investor | acquisition
    employees: int = 10
    region: str = "US"
    website: str = ""
    source: str = "web_research"
    signals: dict = field(default_factory=dict)
    contact: Optional[Contact] = None
    scores: Scores = field(default_factory=Scores)
    id: str = field(default_factory=lambda: _new_id("opp"))
    discovered_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Offer:
    """A personalized offer assembled for a single opportunity."""

    opportunity_id: str
    offer_type: OfferType
    headline: str
    summary: str
    price: float
    roi_estimate: float  # projected annual return in dollars
    assets: list[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: _new_id("off"))

    @property
    def roi_multiple(self) -> float:
        return round(self.roi_estimate / self.price, 1) if self.price else 0.0


@dataclass
class OutreachMessage:
    opportunity_id: str
    channel: Channel
    subject: str
    body: str
    status: str = "drafted"  # drafted | sent | replied | bounced
    sent_at: Optional[datetime] = None
    id: str = field(default_factory=lambda: _new_id("msg"))


@dataclass
class Meeting:
    opportunity_id: str
    scheduled_for: date
    prep: dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: _new_id("mtg"))


@dataclass
class Proposal:
    opportunity_id: str
    offer_id: str
    amount: float
    implementation_plan: list[str] = field(default_factory=list)
    payment_link: str = ""
    won: Optional[bool] = None
    id: str = field(default_factory=lambda: _new_id("prop"))


@dataclass
class Deal:
    """Tracks one opportunity's journey through the pipeline."""

    opportunity_id: str
    stage: Stage = Stage.NEW
    progress: Stage = Stage.NEW  # furthest funnel milestone actually reached
    offer_id: Optional[str] = None
    proposal_id: Optional[str] = None
    channel: Optional[Channel] = None
    amount: float = 0.0
    agent: str = ""  # which AI employee last advanced the deal
    workflow: str = "daily_revenue_loop"
    created_at: datetime = field(default_factory=datetime.utcnow)
    id: str = field(default_factory=lambda: _new_id("deal"))

    def advance(self, stage: Stage) -> None:
        """Move forward in the pipeline.

        Funnel milestones update ``progress`` monotonically; terminal states
        (WON/LOST) set ``stage`` without erasing how far the deal got. WON
        implies the whole funnel was reached.
        """
        if stage is Stage.WON:
            self.progress = Stage.PROPOSAL_SENT
            self.stage = Stage.WON
        elif stage is Stage.LOST:
            self.stage = Stage.LOST
        else:
            if funnel_index(stage) >= funnel_index(self.progress):
                self.progress = stage
            if not self.stage.is_terminal():
                self.stage = stage

    def reached(self, milestone: Stage) -> bool:
        """True if the deal progressed to (at least) ``milestone``."""
        if self.stage is Stage.WON:
            return True
        return funnel_index(self.progress) >= funnel_index(milestone)


@dataclass
class Customer:
    """A won deal that Customer Success now owns."""

    opportunity_id: str
    deal_id: str
    mrr: float
    onboarding_tasks: list[str] = field(default_factory=list)
    health_score: float = 100.0
    churn_risk: float = 0.0
    id: str = field(default_factory=lambda: _new_id("cust"))


@dataclass
class Interaction:
    """A single recorded event, the atomic unit the Learning Engine trains on."""

    opportunity_id: str
    step: str  # discovery | outreach | meeting | proposal | close | success
    channel: Optional[Channel] = None
    offer_type: Optional[OfferType] = None
    industry: str = ""
    agent: str = ""
    outcome: str = ""  # positive | negative | neutral
    value: float = 0.0
    metadata: dict = field(default_factory=dict)
    at: datetime = field(default_factory=datetime.utcnow)
    id: str = field(default_factory=lambda: _new_id("int"))
