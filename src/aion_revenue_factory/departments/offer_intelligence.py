"""Department 2 — Offer Intelligence.

Builds a personalized offer per prospect instead of blasting one message.
Chooses the offer type using what the Learning Engine has found converts best,
prices it from the estimated contract value, and drafts copy via the AI gateway.
"""

from __future__ import annotations

import random

from ..domain import Offer, OfferType, Opportunity
from ..integrations import AIGateway, KnowledgeBase

# Which artifacts ship with each offer type.
_ASSETS = {
    OfferType.AUDIT: ["personalized_audit", "roi_calculator"],
    OfferType.PROPOSAL: ["proposal", "case_study"],
    OfferType.LANDING_PAGE: ["landing_page", "roi_calculator"],
    OfferType.ROI_CALCULATOR: ["roi_calculator"],
    OfferType.CASE_STUDY: ["case_study"],
    OfferType.PILOT: ["pilot_plan", "proposal"],
}

# Offer types the department is allowed to pick between at the top of funnel.
_CANDIDATES = [OfferType.AUDIT, OfferType.ROI_CALCULATOR, OfferType.PILOT]


class OfferIntelligence:
    agent = "Copywriter"

    def __init__(
        self,
        gateway: AIGateway,
        knowledge: KnowledgeBase,
        rng: random.Random | None = None,
        epsilon: float = 0.15,
    ) -> None:
        self.gateway = gateway
        self.knowledge = knowledge
        self._rng = rng or random.Random()
        self.epsilon = epsilon

    def _pain(self, opp: Opportunity) -> str:
        if opp.signals.get("website_tech_gap"):
            return "a leaky, low-converting funnel"
        if opp.signals.get("hiring"):
            return "work that outpaces headcount"
        return "manual, repetitive revenue operations"

    def create_offer(self, opp: Opportunity) -> Offer:
        # Epsilon-greedy: usually exploit the format the Learning Engine says
        # converts best, but keep exploring so weaker-looking offers still get
        # tested and the breakdowns stay honest.
        if self._rng.random() < self.epsilon:
            offer_type = self._rng.choice(_CANDIDATES)
        else:
            offer_type = OfferType(
                self.knowledge.best_offer([o.value for o in _CANDIDATES])
            )

        # Price at ~12% of estimated annual contract value, floored sensibly.
        price = max(1_500.0, round(opp.scores.estimated_contract_value * 0.12, 2))
        roi_estimate = round(price * (3.0 + opp.scores.buying_intent / 40.0), 2)

        context = {
            "company": opp.name,
            "industry": opp.industry,
            "pain": self._pain(opp),
            "outcome": "measurable pipeline and revenue lift",
            "roi_multiple": round(roi_estimate / price, 1),
        }
        summary = self.gateway.generate("audit summary", context)
        headline = f"{offer_type.value.replace('_', ' ').title()} for {opp.name}"

        return Offer(
            opportunity_id=opp.id,
            offer_type=offer_type,
            headline=headline,
            summary=summary,
            price=price,
            roi_estimate=roi_estimate,
            assets=list(_ASSETS[offer_type]),
        )
