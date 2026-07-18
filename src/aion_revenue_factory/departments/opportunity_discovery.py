"""Department 1 — Opportunity Discovery.

Continuously finds businesses, creators, agencies, investors, hiring companies,
and acquisition targets, then scores each one. In production a ``ProspectSource``
wraps real APIs / web research; the ``SyntheticSource`` generates realistic,
seeded prospects so the whole factory runs offline and deterministically.
"""

from __future__ import annotations

import random
from typing import Protocol, runtime_checkable

from ..domain import Contact, Opportunity
from ..scoring import qualify, score_opportunity


@runtime_checkable
class ProspectSource(Protocol):
    def find(self, count: int) -> list[Opportunity]: ...


_INDUSTRIES = [
    "SaaS",
    "E-commerce",
    "Professional Services",
    "Healthcare",
    "Real Estate",
    "Fintech",
    "Marketing Agency",
    "Manufacturing",
]
_KINDS = ["business", "business", "business", "agency", "creator", "investor"]
_FIRST = ["Alex", "Sam", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Jamie"]
_LAST = ["Nguyen", "Patel", "Garcia", "Kim", "Rossi", "Okafor", "Silva", "Haddad"]
_TITLES = ["CEO", "VP Growth", "Head of Ops", "Founder", "CMO", "COO"]


class SyntheticSource:
    """Deterministic prospect generator for offline runs and tests."""

    def __init__(self, seed: int = 42) -> None:
        self._rng = random.Random(seed)

    def find(self, count: int) -> list[Opportunity]:
        rng = self._rng
        out: list[Opportunity] = []
        for i in range(count):
            kind = rng.choice(_KINDS)
            industry = rng.choice(_INDUSTRIES)
            employees = rng.choice([3, 8, 15, 40, 120, 300])
            name = f"{industry.split()[0]}{rng.randint(100, 999)} {kind.title()}"
            contact = Contact(
                name=f"{rng.choice(_FIRST)} {rng.choice(_LAST)}",
                title=rng.choice(_TITLES),
                email=f"lead{rng.randint(1000, 9999)}@example.com",
                confidence=rng.choice([40.0, 55.0, 70.0, 85.0, 95.0]),
            )
            signals = {
                "hiring": rng.random() < 0.45,
                "recent_funding": rng.random() < 0.25,
                "evaluating_vendors": rng.random() < 0.35,
                "website_tech_gap": rng.random() < 0.5,
                "competitor_pressure": rng.random() < 0.3,
            }
            opp = Opportunity(
                name=name,
                industry=industry,
                kind=kind,
                employees=employees,
                region=rng.choice(["US", "EU", "UK", "APAC"]),
                website=f"https://{name.split()[0].lower()}.example.com",
                source=rng.choice(["web_research", "api_enrichment", "referral"]),
                signals=signals,
                contact=contact,
            )
            out.append(opp)
        return out


class OpportunityDiscovery:
    """Finds prospects and attaches scores. Also ranks and qualifies them."""

    agent = "Research Analyst"

    def __init__(self, source: ProspectSource) -> None:
        self.source = source

    def discover(self, count: int) -> list[Opportunity]:
        opportunities = self.source.find(count)
        for opp in opportunities:
            opp.scores = score_opportunity(opp)
        return opportunities

    @staticmethod
    def rank(opportunities: list[Opportunity]) -> list[Opportunity]:
        return sorted(
            opportunities, key=lambda o: o.scores.composite, reverse=True
        )

    @staticmethod
    def qualified(
        opportunities: list[Opportunity], *, min_composite: float = 35.0
    ) -> list[Opportunity]:
        return [o for o in opportunities if qualify(o, min_composite=min_composite)]
