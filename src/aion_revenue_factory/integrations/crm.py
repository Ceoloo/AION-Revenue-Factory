"""The CRM abstraction (Airtable / Supabase in production).

Departments never touch storage directly; they read and write through the
:class:`CRM` protocol. The :class:`InMemoryCRM` is the reference store used by
tests and the offline simulation. An Airtable- or Supabase-backed CRM only has
to satisfy the same protocol.
"""

from __future__ import annotations

from typing import Iterable, Optional, Protocol, runtime_checkable

from ..domain import (
    Customer,
    Deal,
    Interaction,
    Meeting,
    Offer,
    Opportunity,
    OutreachMessage,
    Proposal,
    Stage,
)


@runtime_checkable
class CRM(Protocol):
    def upsert_opportunity(self, opp: Opportunity) -> None: ...
    def upsert_deal(self, deal: Deal) -> None: ...
    def save_offer(self, offer: Offer) -> None: ...
    def save_message(self, msg: OutreachMessage) -> None: ...
    def save_meeting(self, meeting: Meeting) -> None: ...
    def save_proposal(self, proposal: Proposal) -> None: ...
    def save_customer(self, customer: Customer) -> None: ...
    def record_interaction(self, interaction: Interaction) -> None: ...
    def deals(self) -> Iterable[Deal]: ...
    def get_opportunity(self, opp_id: str) -> Optional[Opportunity]: ...


class InMemoryCRM:
    """A simple, inspectable store. Good enough for tests and simulation."""

    def __init__(self) -> None:
        self.opportunities: dict[str, Opportunity] = {}
        self.deals_by_id: dict[str, Deal] = {}
        self.offers: dict[str, Offer] = {}
        self.messages: dict[str, OutreachMessage] = {}
        self.meetings: dict[str, Meeting] = {}
        self.proposals: dict[str, Proposal] = {}
        self.customers: dict[str, Customer] = {}
        self.interactions: list[Interaction] = []

    def upsert_opportunity(self, opp: Opportunity) -> None:
        self.opportunities[opp.id] = opp

    def upsert_deal(self, deal: Deal) -> None:
        self.deals_by_id[deal.id] = deal

    def save_offer(self, offer: Offer) -> None:
        self.offers[offer.id] = offer

    def save_message(self, msg: OutreachMessage) -> None:
        self.messages[msg.id] = msg

    def save_meeting(self, meeting: Meeting) -> None:
        self.meetings[meeting.id] = meeting

    def save_proposal(self, proposal: Proposal) -> None:
        self.proposals[proposal.id] = proposal

    def save_customer(self, customer: Customer) -> None:
        self.customers[customer.id] = customer

    def record_interaction(self, interaction: Interaction) -> None:
        self.interactions.append(interaction)

    def deals(self) -> Iterable[Deal]:
        return list(self.deals_by_id.values())

    def get_opportunity(self, opp_id: str) -> Optional[Opportunity]:
        return self.opportunities.get(opp_id)

    # convenience for the dashboard / tests
    def won_deals(self) -> list[Deal]:
        return [d for d in self.deals_by_id.values() if d.stage is Stage.WON]
