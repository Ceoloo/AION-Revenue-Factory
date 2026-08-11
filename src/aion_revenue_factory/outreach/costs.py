"""Cost abstraction for CAC / ROI.

Providers declare a per-email cost; the AI personalizer declares an estimated
per-generation cost. Aggregating them across a campaign gives the *actual*
variable cost, which the metrics layer combines with a campaign's fixed cost to
produce ROI.

The default numbers are deliberately small, transparent placeholders — override
them per provider/model as real pricing is known.
"""

from __future__ import annotations

from dataclasses import dataclass

# Rough public list prices (USD) as sane defaults; override when known.
DEFAULT_RESEND_COST_PER_EMAIL = 0.0004  # ~ $0.40 / 1k on volume tiers
DEFAULT_SES_COST_PER_EMAIL = 0.0001  # $0.10 / 1k
DEFAULT_GENERATION_COST = 0.01  # blended per personalization call


@dataclass(frozen=True)
class CampaignCosts:
    emails_sent: int
    generations: int
    cost_per_email: float
    cost_per_generation: float
    fixed_cost: float = 0.0

    @property
    def email_cost(self) -> float:
        return round(self.emails_sent * self.cost_per_email, 4)

    @property
    def ai_cost(self) -> float:
        return round(self.generations * self.cost_per_generation, 4)

    @property
    def total(self) -> float:
        return round(self.email_cost + self.ai_cost + self.fixed_cost, 4)
