"""The learning substrate (Founder Memory / Learning Loop in production).

The :class:`KnowledgeBase` holds the weights the factory learns over time:
which channels, offer types, and industries actually convert. Departments read
these weights to bias their choices, and the Learning Engine updates them after
every outcome. This is what makes the system self-improving rather than static.
"""

from __future__ import annotations

from collections import defaultdict


class KnowledgeBase:
    """Multiplicative preference weights, all starting neutral at 1.0.

    Weights are nudged up on positive outcomes and down on negative ones, then
    clamped to a sane band so a single lucky (or unlucky) day cannot dominate.
    """

    MIN_WEIGHT = 0.25
    MAX_WEIGHT = 3.0

    def __init__(self) -> None:
        self.channel_weight: dict[str, float] = defaultdict(lambda: 1.0)
        self.offer_weight: dict[str, float] = defaultdict(lambda: 1.0)
        self.industry_weight: dict[str, float] = defaultdict(lambda: 1.0)
        self.wins: int = 0
        self.losses: int = 0

    def _nudge(self, table: dict, key: str, delta: float) -> None:
        new = table[key] * (1.0 + delta)
        table[key] = max(self.MIN_WEIGHT, min(self.MAX_WEIGHT, new))

    def reinforce(
        self,
        *,
        channel: str | None,
        offer_type: str | None,
        industry: str | None,
        positive: bool,
        strength: float = 0.15,
    ) -> None:
        delta = strength if positive else -strength
        if channel:
            self._nudge(self.channel_weight, channel, delta)
        if offer_type:
            self._nudge(self.offer_weight, offer_type, delta)
        if industry:
            self._nudge(self.industry_weight, industry, delta)
        if positive:
            self.wins += 1
        else:
            self.losses += 1

    def best_channel(self, channels: list[str]) -> str:
        return max(channels, key=lambda c: self.channel_weight[c])

    def best_offer(self, offer_types: list[str]) -> str:
        return max(offer_types, key=lambda o: self.offer_weight[o])

    def snapshot(self) -> dict:
        return {
            "channel_weight": {k: round(v, 3) for k, v in self.channel_weight.items()},
            "offer_weight": {k: round(v, 3) for k, v in self.offer_weight.items()},
            "industry_weight": {
                k: round(v, 3) for k, v in self.industry_weight.items()
            },
            "wins": self.wins,
            "losses": self.losses,
        }
