"""Department 8 — Learning Engine.

Every interaction becomes training data. The engine turns recorded outcomes into
reinforcement signals on the KnowledgeBase (which channel, offer, and industry
convert) so tomorrow's offers and outreach are chosen better than today's.
This is the mechanism behind the self-improving loop.
"""

from __future__ import annotations

from ..domain import Channel, Interaction, OfferType
from ..integrations import KnowledgeBase


class LearningEngine:
    agent = "Revenue Analyst"

    def __init__(self, knowledge: KnowledgeBase) -> None:
        self.knowledge = knowledge

    def learn_from(self, interaction: Interaction) -> None:
        """Reinforce weights from a single recorded interaction."""
        if interaction.outcome not in ("positive", "negative"):
            return
        positive = interaction.outcome == "positive"
        # Closes carry the strongest signal; a positive reply is worth more than
        # a single non-reply, so the high-volume top-of-funnel noise does not
        # drown out what actually converts.
        if interaction.step == "close":
            strength = 0.2
        elif positive:
            strength = 0.08
        else:
            strength = 0.03
        self.knowledge.reinforce(
            channel=interaction.channel.value if interaction.channel else None,
            offer_type=interaction.offer_type.value if interaction.offer_type else None,
            industry=interaction.industry or None,
            positive=positive,
            strength=strength,
        )

    def learn_batch(self, interactions: list[Interaction]) -> dict:
        for interaction in interactions:
            self.learn_from(interaction)
        return self.knowledge.snapshot()

    def questions_answered(self, interactions: list[Interaction]) -> dict:
        """Summarize the qualitative 'why' the vision asks for."""
        closes = [i for i in interactions if i.step == "close"]
        wins = [i for i in closes if i.outcome == "positive"]
        losses = [i for i in closes if i.outcome == "negative"]

        def _top(items: list[Interaction], attr: str) -> str | None:
            counts: dict[str, int] = {}
            for it in items:
                val = getattr(it, attr)
                key = val.value if hasattr(val, "value") else val
                if key:
                    counts[key] = counts.get(key, 0) + 1
            return max(counts, key=counts.get) if counts else None

        return {
            "why_they_bought": {
                "top_channel": _top(wins, "channel"),
                "top_offer": _top(wins, "offer_type"),
                "top_industry": _top(wins, "industry"),
            },
            "why_they_rejected": {
                "top_channel": _top(losses, "channel"),
                "top_offer": _top(losses, "offer_type"),
            },
            "pricing_that_converted": round(
                sum(i.value for i in wins) / len(wins), 2
            )
            if wins
            else None,
        }
