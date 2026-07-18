"""Opportunity scoring.

Turns raw prospect signals into the five numbers every opportunity carries:
revenue score, urgency, buying intent, contact confidence, and estimated
contract value. Deterministic and pure so it is trivially testable and the
ranking is reproducible.
"""

from __future__ import annotations

from .domain import Contact, Opportunity, Scores

# Rough per-seat annual value the factory can capture, by prospect kind.
_VALUE_PER_EMPLOYEE = {
    "business": 900.0,
    "agency": 1_400.0,
    "creator": 300.0,
    "investor": 2_000.0,
    "acquisition": 5_000.0,
}


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def score_opportunity(opp: Opportunity) -> Scores:
    """Compute and return scores for an opportunity (does not mutate it)."""
    signals = opp.signals

    # Buying intent: explicit demand signals dominate.
    intent = 20.0
    intent += 30.0 if signals.get("hiring") else 0.0
    intent += 25.0 if signals.get("recent_funding") else 0.0
    intent += 15.0 if signals.get("evaluating_vendors") else 0.0
    intent += 10.0 if signals.get("website_tech_gap") else 0.0
    buying_intent = _clamp(intent)

    # Urgency: time-sensitive triggers.
    urgency = 15.0
    urgency += 35.0 if signals.get("recent_funding") else 0.0
    urgency += 25.0 if signals.get("hiring") else 0.0
    urgency += 20.0 if signals.get("competitor_pressure") else 0.0
    urgency_score = _clamp(urgency)

    # Contact confidence: do we have a reachable decision maker?
    contact_confidence = opp.contact.confidence if opp.contact else 0.0

    # Estimated contract value scales with size and kind.
    per = _VALUE_PER_EMPLOYEE.get(opp.kind, 900.0)
    ecv = per * max(opp.employees, 1)
    if signals.get("recent_funding"):
        ecv *= 1.5
    estimated_contract_value = round(ecv, 2)

    # Revenue score blends value potential with reachability and fit.
    value_component = _clamp(estimated_contract_value / 1_000.0)  # $100k -> 100
    fit = 60.0 if opp.kind in ("business", "agency") else 40.0
    revenue = 0.5 * value_component + 0.3 * fit + 0.2 * contact_confidence
    revenue_score = _clamp(revenue)

    return Scores(
        revenue_score=round(revenue_score, 2),
        urgency_score=round(urgency_score, 2),
        buying_intent=round(buying_intent, 2),
        contact_confidence=round(contact_confidence, 2),
        estimated_contract_value=estimated_contract_value,
    )


def qualify(opp: Opportunity, *, min_composite: float = 35.0) -> bool:
    """Cheap gate so the outreach workforce only spends cycles on real leads."""
    return opp.scores.composite >= min_composite
