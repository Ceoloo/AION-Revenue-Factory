"""Department 4 — Meeting Preparation.

Before every booked meeting the factory assembles a briefing pack: company
profile, likely decision makers, pain points, competitors, probable objections,
and a pricing recommendation — like handing the rep a sales engineer.
"""

from __future__ import annotations

from datetime import date, timedelta

from ..domain import Meeting, Offer, Opportunity


class MeetingPrep:
    agent = "Research Analyst"

    def prepare(self, opp: Opportunity, offer: Offer, when: date | None = None) -> Meeting:
        pain_points = []
        if opp.signals.get("website_tech_gap"):
            pain_points.append("Low-converting website / funnel")
        if opp.signals.get("hiring"):
            pain_points.append("Scaling faster than headcount")
        if opp.signals.get("competitor_pressure"):
            pain_points.append("Losing ground to competitors")
        if not pain_points:
            pain_points.append("Manual revenue operations")

        objections = [
            "Is now the right time?",
            "How is this different from tools we already have?",
            "What is the real ROI and payback period?",
        ]
        if offer.price > 10_000:
            objections.append("This is above our current budget.")

        prep = {
            "company_profile": {
                "name": opp.name,
                "industry": opp.industry,
                "size": opp.employees,
                "region": opp.region,
            },
            "decision_makers": [
                {
                    "name": opp.contact.name if opp.contact else "Unknown",
                    "title": opp.contact.title if opp.contact else "Unknown",
                }
            ],
            "pain_points": pain_points,
            "competitors": ["Incumbent tooling", "In-house spreadsheets"],
            "objections": objections,
            "pricing_recommendation": {
                "list_price": offer.price,
                "floor": round(offer.price * 0.85, 2),
                "expected_roi_multiple": offer.roi_multiple,
            },
        }
        return Meeting(
            opportunity_id=opp.id,
            scheduled_for=when or (date.today() + timedelta(days=3)),
            prep=prep,
        )
