"""The Hermes-style orchestrator.

Composes the eight departments into the daily autonomous workflow described in
the vision:

    find -> research -> rank -> offer -> outreach -> follow up -> book meeting
    -> prep -> proposal -> coach -> close -> onboard -> update CRM -> learn -> repeat

Prospect responses are produced by an injectable, seeded ``ResponseModel`` so a
run is fully deterministic and offline. Swap it for a live model that reads real
replies and the same orchestration drives production.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from .departments import (
    CustomerSuccess,
    DealCoach,
    LearningEngine,
    MeetingPrep,
    OfferIntelligence,
    OpportunityDiscovery,
    OutreachWorkforce,
    ProposalGenerator,
    SyntheticSource,
)
from .domain import Deal, Interaction, Stage
from .integrations import InMemoryCRM, KnowledgeBase, TemplateGateway


@dataclass
class ResponseModel:
    """Seeded model of how prospects react at each funnel stage.

    Probabilities are derived from the opportunity's own scores so better leads
    genuinely convert more often, which is what lets the Learning Engine find
    real signal.
    """

    seed: int = 7
    _rng: random.Random = field(default_factory=lambda: random.Random(7), repr=False)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)

    def replies(self, buying_intent: float) -> bool:
        return self._rng.random() < (0.10 + buying_intent / 250.0)

    def books_meeting(self, urgency: float) -> bool:
        return self._rng.random() < (0.35 + urgency / 300.0)

    def closes(self, probability: float) -> bool:
        return self._rng.random() < probability


@dataclass
class DayResult:
    day: int
    discovered: int
    qualified: int
    contacted: int
    replied: int
    meetings: int
    proposals: int
    won: int
    revenue: float
    interactions: list[Interaction]


class RevenueFactory:
    """Owns the departments, shared CRM, and knowledge base across days."""

    def __init__(
        self,
        crm: InMemoryCRM | None = None,
        knowledge: KnowledgeBase | None = None,
        source_seed: int = 42,
        response_seed: int = 7,
    ) -> None:
        self.crm = crm or InMemoryCRM()
        self.knowledge = knowledge or KnowledgeBase()
        gateway = TemplateGateway()
        # Separate, seeded RNGs keep exploration deterministic and reproducible.
        offer_rng = random.Random(source_seed + 1)
        channel_rng = random.Random(source_seed + 2)

        self.discovery = OpportunityDiscovery(SyntheticSource(seed=source_seed))
        self.offers = OfferIntelligence(gateway, self.knowledge, rng=offer_rng)
        self.outreach = OutreachWorkforce(gateway, self.knowledge, rng=channel_rng)
        self.meeting_prep = MeetingPrep()
        self.proposals = ProposalGenerator(gateway)
        self.coach = DealCoach(self.knowledge)
        self.success = CustomerSuccess()
        self.learning = LearningEngine(self.knowledge)

        self.responses = ResponseModel(seed=response_seed)
        self._day = 0

    def run_day(self, prospects: int = 50) -> DayResult:
        """Execute one full autonomous revenue cycle."""
        self._day += 1
        interactions: list[Interaction] = []
        contacted = replied = meetings = proposals = won = 0
        revenue = 0.0

        opportunities = self.discovery.discover(prospects)
        for opp in opportunities:
            self.crm.upsert_opportunity(opp)
        qualified = self.discovery.qualified(self.discovery.rank(opportunities))

        for opp in qualified:
            offer = self.offers.create_offer(opp)
            self.crm.save_offer(offer)

            channel = self.outreach.choose_channel(opp)
            deal = Deal(
                opportunity_id=opp.id,
                offer_id=offer.id,
                channel=channel,
                agent=self.outreach.agent_for(channel),
            )

            msg = self.outreach.compose(opp, offer, channel)
            self.outreach.send(msg)
            self.crm.save_message(msg)
            deal.advance(Stage.CONTACTED)
            contacted += 1

            base_interaction = dict(
                opportunity_id=opp.id,
                channel=channel,
                offer_type=offer.offer_type,
                industry=opp.industry,
            )

            if not self.responses.replies(opp.scores.buying_intent):
                deal.advance(Stage.LOST)
                self.crm.upsert_deal(deal)
                interactions.append(
                    Interaction(step="outreach", outcome="negative", agent=deal.agent, **base_interaction)
                )
                continue

            deal.advance(Stage.REPLIED)
            replied += 1
            interactions.append(
                Interaction(step="outreach", outcome="positive", agent=deal.agent, **base_interaction)
            )

            if not self.responses.books_meeting(opp.scores.urgency_score):
                self.crm.upsert_deal(deal)
                continue

            meeting = self.meeting_prep.prepare(opp, offer)
            self.crm.save_meeting(meeting)
            deal.advance(Stage.MEETING_BOOKED)
            meetings += 1

            proposal = self.proposals.generate(opp, offer)
            recs = self.coach.recommend(opp, offer, proposal)
            if recs.get("discount"):
                pct = recs["discount"]["offer_pct"]
                proposal.amount = round(proposal.amount * (1 - pct / 100.0), 2)
            self.crm.save_proposal(proposal)
            deal.advance(Stage.PROPOSAL_SENT)
            deal.proposal_id = proposal.id
            proposals += 1

            probability = self.coach.close_probability(opp, offer)
            if self.responses.closes(probability):
                proposal.won = True
                deal.advance(Stage.WON)
                deal.amount = proposal.amount
                won += 1
                revenue += proposal.amount
                customer = self.success.onboard(opp, deal)
                self.crm.save_customer(customer)
                interactions.append(
                    Interaction(
                        step="close", outcome="positive", agent=self.coach.agent,
                        value=proposal.amount, **base_interaction
                    )
                )
            else:
                proposal.won = False
                deal.advance(Stage.LOST)
                interactions.append(
                    Interaction(
                        step="close", outcome="negative", agent=self.coach.agent,
                        value=proposal.amount, **base_interaction
                    )
                )
            self.crm.upsert_deal(deal)

        # Feed everything back into the learning loop for tomorrow.
        for interaction in interactions:
            self.crm.record_interaction(interaction)
        self.learning.learn_batch(interactions)

        return DayResult(
            day=self._day,
            discovered=len(opportunities),
            qualified=len(qualified),
            contacted=contacted,
            replied=replied,
            meetings=meetings,
            proposals=proposals,
            won=won,
            revenue=round(revenue, 2),
            interactions=interactions,
        )

    def run_days(self, days: int, prospects: int = 50) -> list[DayResult]:
        return [self.run_day(prospects) for _ in range(days)]
