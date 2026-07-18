"""Department 5 — Proposal Generator.

After a meeting, generates the proposal, an implementation plan, and a payment
link within minutes. The ``won`` flag is set later by the close step / Deal
Coach; this department only produces the artifact.
"""

from __future__ import annotations

from ..domain import Offer, Opportunity, Proposal
from ..integrations import AIGateway


class ProposalGenerator:
    agent = "Proposal Writer"

    def __init__(self, gateway: AIGateway) -> None:
        self.gateway = gateway

    def generate(self, opp: Opportunity, offer: Offer, amount: float | None = None) -> Proposal:
        amount = amount if amount is not None else offer.price
        context = {
            "company": opp.name,
            "industry": opp.industry,
            "pain": "manual, repetitive revenue operations",
            "outcome": "measurable revenue lift",
            "roi_multiple": offer.roi_multiple,
        }
        # The narrative body is generated but stored on the offer summary path;
        # here we keep the structured plan the customer signs off on.
        _ = self.gateway.generate("proposal narrative", context)
        plan = [
            "Week 1: Discovery + data connection (Airtable / Supabase)",
            "Week 2: Configure AI employees and offer templates",
            "Week 3: Launch outreach workflows, begin booking meetings",
            "Week 4: Review pipeline, tune prompts, expand volume",
        ]
        return Proposal(
            opportunity_id=opp.id,
            offer_id=offer.id,
            amount=round(amount, 2),
            implementation_plan=plan,
            payment_link=f"https://pay.aion.example/checkout/{offer.id}",
        )
