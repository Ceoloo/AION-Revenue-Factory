"""Department 7 — Customer Success.

Once a deal is won, creates onboarding, tracks account health, flags churn risk,
and surfaces upsell opportunities. MRR is derived from the deal amount treated
as an annual contract.
"""

from __future__ import annotations

from ..domain import Customer, Deal, Opportunity


class CustomerSuccess:
    agent = "Customer Success"

    def onboard(self, opp: Opportunity, deal: Deal) -> Customer:
        mrr = round(deal.amount / 12.0, 2)
        tasks = [
            "Send welcome + kickoff scheduling",
            "Connect data sources (Airtable / Supabase)",
            "Configure AI employees for the account",
            "Set first 30-day success milestones",
            "Schedule day-14 value check-in",
        ]
        # Early churn risk read from how they bought.
        churn_risk = 15.0
        if opp.scores.buying_intent < 40:
            churn_risk += 20.0
        if deal.amount > 20_000:
            churn_risk += 10.0  # bigger deals, higher expectations
        health = round(max(0.0, 100.0 - churn_risk), 2)

        return Customer(
            opportunity_id=opp.id,
            deal_id=deal.id,
            mrr=mrr,
            onboarding_tasks=tasks,
            health_score=health,
            churn_risk=round(min(churn_risk, 100.0), 2),
        )

    @staticmethod
    def recommend_upsell(customer: Customer) -> str | None:
        if customer.health_score >= 80 and customer.mrr >= 1_000:
            return "Expand seats + add referral program"
        return None
