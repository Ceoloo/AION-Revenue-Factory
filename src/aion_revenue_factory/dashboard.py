"""The Revenue Dashboard.

Computes the live metrics in the vision from whatever is in the CRM: revenue,
pipeline, MRR/ARR, close rate, deal size, CAC/LTV, velocity, reply rate, booked
calls, proposal win %, and revenue broken down by agent, workflow, offer, and
industry.
"""

from __future__ import annotations

from collections import defaultdict

from .domain import Stage
from .integrations import InMemoryCRM

# Assumed blended cost to acquire (outreach + tooling) per contacted lead.
DEFAULT_CAC_PER_CONTACT = 8.0
# Assumed customer lifetime in months for LTV.
DEFAULT_LIFETIME_MONTHS = 24


class Dashboard:
    def __init__(self, crm: InMemoryCRM) -> None:
        self.crm = crm

    def metrics(self, today_revenue: float = 0.0) -> dict:
        deals = list(self.crm.deals())
        won = [d for d in deals if d.stage is Stage.WON]
        contacted = [d for d in deals if d.reached(Stage.CONTACTED)]
        replied = [d for d in deals if d.reached(Stage.REPLIED)]
        meetings = [d for d in deals if d.reached(Stage.MEETING_BOOKED)]
        proposals = [d for d in deals if d.reached(Stage.PROPOSAL_SENT)]

        revenue = sum(d.amount for d in won)
        mrr = sum(c.mrr for c in self.crm.customers.values())
        avg_deal = revenue / len(won) if won else 0.0
        close_rate = len(won) / len(contacted) if contacted else 0.0
        reply_rate = len(replied) / len(contacted) if contacted else 0.0
        proposal_win = len(won) / len(proposals) if proposals else 0.0

        cac = (
            (len(contacted) * DEFAULT_CAC_PER_CONTACT) / len(won) if won else 0.0
        )
        ltv = (mrr / len(won) * DEFAULT_LIFETIME_MONTHS) if won else 0.0

        return {
            "today_revenue": round(today_revenue, 2),
            "total_revenue": round(revenue, 2),
            "pipeline_value": round(self._pipeline_value(deals), 2),
            "mrr": round(mrr, 2),
            "arr": round(mrr * 12, 2),
            "close_rate": round(close_rate, 4),
            "avg_deal_size": round(avg_deal, 2),
            "cac": round(cac, 2),
            "ltv": round(ltv, 2),
            "ltv_cac_ratio": round(ltv / cac, 2) if cac else 0.0,
            "lead_velocity": len(contacted),
            "reply_rate": round(reply_rate, 4),
            "booked_calls": len(meetings),
            "proposal_win_rate": round(proposal_win, 4),
            "revenue_by_agent": self._by(won, key=lambda d: d.agent),
            "revenue_by_workflow": self._by(won, key=lambda d: d.workflow),
            "revenue_by_offer": self._by_offer(won),
            "revenue_by_industry": self._by_industry(won),
        }

    # Probability an open deal at each stage eventually closes.
    _STAGE_WEIGHT = {
        Stage.CONTACTED: 0.05,
        Stage.REPLIED: 0.15,
        Stage.MEETING_BOOKED: 0.35,
        Stage.PROPOSAL_SENT: 0.60,
    }

    def _pipeline_value(self, deals) -> float:
        """Probability-weighted value of every still-open deal."""
        total = 0.0
        for d in deals:
            if d.stage.is_terminal():
                continue
            weight = self._STAGE_WEIGHT.get(d.stage, 0.0)
            if not weight:
                continue
            offer = self.crm.offers.get(d.offer_id) if d.offer_id else None
            price = offer.price if offer else 0.0
            total += price * weight
        return total

    @staticmethod
    def _by(deals, key) -> dict:
        out: dict[str, float] = defaultdict(float)
        for d in deals:
            out[key(d) or "unknown"] += d.amount
        return {k: round(v, 2) for k, v in sorted(out.items(), key=lambda x: -x[1])}

    def _by_offer(self, deals) -> dict:
        out: dict[str, float] = defaultdict(float)
        for d in deals:
            offer = self.crm.offers.get(d.offer_id) if d.offer_id else None
            key = offer.offer_type.value if offer else "unknown"
            out[key] += d.amount
        return {k: round(v, 2) for k, v in sorted(out.items(), key=lambda x: -x[1])}

    def _by_industry(self, deals) -> dict:
        out: dict[str, float] = defaultdict(float)
        for d in deals:
            opp = self.crm.get_opportunity(d.opportunity_id)
            key = opp.industry if opp else "unknown"
            out[key] += d.amount
        return {k: round(v, 2) for k, v in sorted(out.items(), key=lambda x: -x[1])}
