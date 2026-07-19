"""Write-through CRM base for live backends (Airtable, Supabase).

A live CRM must satisfy the same ``CRM`` protocol the departments use — including
the read methods the dashboard needs (``deals()``, ``get_opportunity()``). Rather
than round-trip every read to the backend, these adapters keep a local
``InMemoryCRM`` as a write-through cache: reads are served locally, and every
write is *also* pushed to the real backend via ``_persist``.

Subclasses implement one method: ``_persist(table, record)``.
"""

from __future__ import annotations

from ...domain import (
    Customer,
    Deal,
    Interaction,
    Meeting,
    Offer,
    Opportunity,
    OutreachMessage,
    Proposal,
)
from ..crm import InMemoryCRM


def _opportunity_fields(o: Opportunity) -> dict:
    return {
        "id": o.id,
        "name": o.name,
        "industry": o.industry,
        "kind": o.kind,
        "employees": o.employees,
        "region": o.region,
        "website": o.website,
        "source": o.source,
        "revenue_score": o.scores.revenue_score,
        "urgency_score": o.scores.urgency_score,
        "buying_intent": o.scores.buying_intent,
        "contact_confidence": o.scores.contact_confidence,
        "estimated_contract_value": o.scores.estimated_contract_value,
        "composite": o.scores.composite,
        "contact_name": o.contact.name if o.contact else "",
        "contact_email": o.contact.email if o.contact else "",
    }


def _deal_fields(d: Deal) -> dict:
    return {
        "id": d.id,
        "opportunity_id": d.opportunity_id,
        "stage": d.stage.value,
        "progress": d.progress.value,
        "channel": d.channel.value if d.channel else "",
        "amount": d.amount,
        "agent": d.agent,
        "workflow": d.workflow,
        "offer_id": d.offer_id or "",
        "proposal_id": d.proposal_id or "",
    }


def _offer_fields(o: Offer) -> dict:
    return {
        "id": o.id,
        "opportunity_id": o.opportunity_id,
        "offer_type": o.offer_type.value,
        "headline": o.headline,
        "summary": o.summary,
        "price": o.price,
        "roi_estimate": o.roi_estimate,
    }


def _message_fields(m: OutreachMessage) -> dict:
    return {
        "id": m.id,
        "opportunity_id": m.opportunity_id,
        "channel": m.channel.value,
        "subject": m.subject,
        "body": m.body,
        "status": m.status,
        "sent_at": m.sent_at.isoformat() if m.sent_at else "",
    }


def _meeting_fields(m: Meeting) -> dict:
    return {
        "id": m.id,
        "opportunity_id": m.opportunity_id,
        "scheduled_for": m.scheduled_for.isoformat(),
    }


def _proposal_fields(p: Proposal) -> dict:
    return {
        "id": p.id,
        "opportunity_id": p.opportunity_id,
        "offer_id": p.offer_id,
        "amount": p.amount,
        "payment_link": p.payment_link,
        "won": p.won,
    }


def _customer_fields(c: Customer) -> dict:
    return {
        "id": c.id,
        "opportunity_id": c.opportunity_id,
        "deal_id": c.deal_id,
        "mrr": c.mrr,
        "health_score": c.health_score,
        "churn_risk": c.churn_risk,
    }


def _interaction_fields(i: Interaction) -> dict:
    return {
        "id": i.id,
        "opportunity_id": i.opportunity_id,
        "step": i.step,
        "channel": i.channel.value if i.channel else "",
        "offer_type": i.offer_type.value if i.offer_type else "",
        "industry": i.industry,
        "agent": i.agent,
        "outcome": i.outcome,
        "value": i.value,
    }


class WriteThroughCRM(InMemoryCRM):
    """InMemoryCRM that mirrors every write to a real backend.

    ``tables`` maps a logical entity name to the backend table/collection name,
    so the same adapter works whatever the user named their tables.
    """

    DEFAULT_TABLES = {
        "opportunities": "Opportunities",
        "deals": "Deals",
        "offers": "Offers",
        "messages": "Messages",
        "meetings": "Meetings",
        "proposals": "Proposals",
        "customers": "Customers",
        "interactions": "Interactions",
    }

    def __init__(self, tables: dict | None = None) -> None:
        super().__init__()
        self.tables = {**self.DEFAULT_TABLES, **(tables or {})}

    # Subclasses implement the actual persistence.
    def _persist(self, table: str, record: dict) -> None:  # pragma: no cover
        raise NotImplementedError

    def upsert_opportunity(self, opp: Opportunity) -> None:
        super().upsert_opportunity(opp)
        self._persist(self.tables["opportunities"], _opportunity_fields(opp))

    def upsert_deal(self, deal: Deal) -> None:
        super().upsert_deal(deal)
        self._persist(self.tables["deals"], _deal_fields(deal))

    def save_offer(self, offer: Offer) -> None:
        super().save_offer(offer)
        self._persist(self.tables["offers"], _offer_fields(offer))

    def save_message(self, msg: OutreachMessage) -> None:
        super().save_message(msg)
        self._persist(self.tables["messages"], _message_fields(msg))

    def save_meeting(self, meeting: Meeting) -> None:
        super().save_meeting(meeting)
        self._persist(self.tables["meetings"], _meeting_fields(meeting))

    def save_proposal(self, proposal: Proposal) -> None:
        super().save_proposal(proposal)
        self._persist(self.tables["proposals"], _proposal_fields(proposal))

    def save_customer(self, customer: Customer) -> None:
        super().save_customer(customer)
        self._persist(self.tables["customers"], _customer_fields(customer))

    def record_interaction(self, interaction: Interaction) -> None:
        super().record_interaction(interaction)
        self._persist(self.tables["interactions"], _interaction_fields(interaction))
