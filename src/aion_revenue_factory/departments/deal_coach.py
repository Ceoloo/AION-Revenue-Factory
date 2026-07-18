"""Department 6 — Deal Coach.

During negotiation, recommends discounts, upsells, objection handling, timing,
and an overall strategy based on what has historically converted (the learned
weights). Also estimates a close probability the pipeline uses to decide wins.
"""

from __future__ import annotations

from ..domain import Offer, Opportunity, Proposal
from ..integrations import KnowledgeBase


class DealCoach:
    agent = "Negotiator"

    def __init__(self, knowledge: KnowledgeBase) -> None:
        self.knowledge = knowledge

    def close_probability(self, opp: Opportunity, offer: Offer) -> float:
        """0-1 probability blending intent, fit, and learned offer weight."""
        base = 0.20
        base += opp.scores.buying_intent / 300.0  # up to +0.33
        base += opp.scores.urgency_score / 500.0  # up to +0.20
        base += (offer.roi_multiple - 3.0) / 40.0  # reward strong ROI
        base *= self.knowledge.offer_weight[offer.offer_type.value]
        return max(0.03, min(0.9, base))

    def recommend(self, opp: Opportunity, offer: Offer, proposal: Proposal) -> dict:
        recs: dict = {"strategy": "anchor on ROI, then de-risk with a pilot"}

        # Discounting: only when urgency is low and the deal is large.
        if opp.scores.urgency_score < 40 and offer.price > 8_000:
            recs["discount"] = {
                "offer_pct": 10,
                "condition": "annual commitment",
            }
        else:
            recs["discount"] = None

        # Upsell when the account is big and clearly buying.
        if opp.employees >= 40 and opp.scores.buying_intent >= 60:
            recs["upsell"] = "Add managed outreach + quarterly optimization retainer"

        recs["objection_handling"] = {
            "budget": "Reframe as revenue generated, not cost incurred.",
            "timing": "Offer a 2-week paid pilot to prove ROI before annual.",
            "trust": f"Share the {offer.offer_type.value} results up front.",
        }
        recs["timing"] = (
            "Push to close this week" if opp.scores.urgency_score >= 60 else "Nurture 1-2 weeks"
        )
        return recs
