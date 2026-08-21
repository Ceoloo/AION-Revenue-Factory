"""The Hermes-style orchestrator.

Composes the eight departments into the daily autonomous workflow described in
the vision:

    find -> research -> rank -> offer -> outreach -> follow up -> book meeting
    -> prep -> proposal -> coach -> close -> onboard -> update CRM -> learn -> repeat

Prospect responses are produced by an injectable, seeded ``ResponseModel`` so a
run is fully deterministic and offline. Swap it for a live model that reads real
replies and the same orchestration drives production.

Every meaningful step also emits a versioned AION envelope event through an
injectable ``EventSink`` (default ``NullSink`` = no-op), threaded by one
``correlation_id`` per opportunity so a customer journey can be reconstructed
end-to-end. Emission never touches the seeded RNGs, so runs stay deterministic.
"""

from __future__ import annotations

import random
import uuid
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
from .domain import Channel, Deal, Interaction, Stage
from .integrations import InMemoryCRM, KnowledgeBase, TemplateGateway
from .integrations.aion_events import new_event, redact_payload
from .integrations.event_sink import NullSink

# Channels with a canonical AION outreach event type. Other channels (SMS, cold
# call, voice AI) have no canonical outreach.* type yet, so no channel-specific
# event is emitted for them (the workflow/deal still captures the activity).
_OUTREACH_EVENT_BY_CHANNEL = {
    Channel.EMAIL: "outreach.email_sent",
    Channel.LINKEDIN: "outreach.linkedin_sent",
}


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
        crm=None,
        knowledge: KnowledgeBase | None = None,
        source_seed: int = 42,
        response_seed: int = 7,
        gateway=None,
        source=None,
        outreach_send=None,
        event_sink=None,
        environment: str = "development",
    ) -> None:
        """Wire the departments together.

        Every external dependency is injectable so the same orchestration runs
        offline (the defaults) or against live services:

        - ``gateway``: an AIGateway (default TemplateGateway; inject
          AnthropicGateway for real LLM copy).
        - ``crm``: a CRM (default InMemoryCRM; inject AirtableCRM / SupabaseCRM /
          SupabaseRevenueAdapter).
        - ``source``: a ProspectSource (default SyntheticSource; inject
          HttpProspectSource for real enrichment APIs).
        - ``outreach_send``: a callable that actually sends a message (default
          offline no-op; inject SmtpSender / WebhookSender).
        - ``event_sink``: an EventSink (default NullSink = no-op; inject
          HttpTelemetrySink to publish AION envelope events).
        """
        self.crm = crm or InMemoryCRM()
        self.knowledge = knowledge or KnowledgeBase()
        gateway = gateway or TemplateGateway()
        # Separate, seeded RNGs keep exploration deterministic and reproducible.
        offer_rng = random.Random(source_seed + 1)
        channel_rng = random.Random(source_seed + 2)

        prospect_source = source or SyntheticSource(seed=source_seed)
        self.discovery = OpportunityDiscovery(prospect_source)
        self.offers = OfferIntelligence(gateway, self.knowledge, rng=offer_rng)
        outreach_kwargs = {"rng": channel_rng}
        if outreach_send is not None:
            outreach_kwargs["send"] = outreach_send
        self.outreach = OutreachWorkforce(gateway, self.knowledge, **outreach_kwargs)
        self.meeting_prep = MeetingPrep()
        self.proposals = ProposalGenerator(gateway)
        self.coach = DealCoach(self.knowledge)
        self.success = CustomerSuccess()
        self.learning = LearningEngine(self.knowledge)

        self.responses = ResponseModel(seed=response_seed)
        # Event emission. NullSink keeps offline runs side-effect free; inject
        # any EventSink (e.g. HttpTelemetrySink) to publish envelope events.
        self.events = event_sink or NullSink()
        self.environment = environment
        self._day = 0

    def _emit(self, event_type, correlation_id, *, payload=None, metrics=None,
              workflow_id=None) -> None:
        """Build and publish one AION envelope event (payload is redacted)."""
        event = new_event(
            event_type,
            payload=redact_payload(payload or {}),
            metrics=metrics or {},
            correlation_id=correlation_id,
            environment=self.environment,
        )
        if workflow_id:
            event.workflow_id = workflow_id
        self.events.emit(event)

    def run_day(self, prospects: int = 50) -> DayResult:
        """Execute one full autonomous revenue cycle."""
        self._day += 1
        workflow_id = str(uuid.uuid4())
        self._emit("workflow.started", workflow_id, workflow_id=workflow_id,
                   payload={"prospects": prospects})
        correlation: dict[str, str] = {}

        interactions: list[Interaction] = []
        contacted = replied = meetings = proposals = won = 0
        revenue = 0.0

        opportunities = self.discovery.discover(prospects)
        for opp in opportunities:
            self.crm.upsert_opportunity(opp)
            correlation[opp.id] = str(uuid.uuid4())
            self._emit(
                "lead.discovered", correlation[opp.id], workflow_id=workflow_id,
                payload={"opportunity_id": opp.id, "company": opp.name,
                         "industry": opp.industry, "source": opp.source},
                metrics={"composite": opp.scores.composite,
                         "estimated_contract_value": opp.scores.estimated_contract_value},
            )
        qualified = self.discovery.qualified(self.discovery.rank(opportunities))

        for opp in qualified:
            cid = correlation[opp.id]
            self._emit(
                "lead.qualified", cid, workflow_id=workflow_id,
                payload={"opportunity_id": opp.id, "industry": opp.industry},
                metrics={"composite": opp.scores.composite,
                         "buying_intent": opp.scores.buying_intent,
                         "urgency": opp.scores.urgency_score},
            )
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
            outreach_event = _OUTREACH_EVENT_BY_CHANNEL.get(channel)
            if outreach_event:
                self._emit(outreach_event, cid, workflow_id=workflow_id,
                           payload={"opportunity_id": opp.id, "channel": channel.value})

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
            self._emit("appointment.booked", cid, workflow_id=workflow_id,
                       payload={"opportunity_id": opp.id,
                                "scheduled_for": meeting.scheduled_for.isoformat()})

            proposal = self.proposals.generate(opp, offer)
            recs = self.coach.recommend(opp, offer, proposal)
            if recs.get("discount"):
                pct = recs["discount"]["offer_pct"]
                proposal.amount = round(proposal.amount * (1 - pct / 100.0), 2)
            self.crm.save_proposal(proposal)
            deal.advance(Stage.PROPOSAL_SENT)
            deal.proposal_id = proposal.id
            proposals += 1
            self._emit("proposal.sent", cid, workflow_id=workflow_id,
                       payload={"opportunity_id": opp.id, "proposal_id": proposal.id,
                                "offer_id": offer.id},
                       metrics={"amount": proposal.amount})

            probability = self.coach.close_probability(opp, offer)
            if self.responses.closes(probability):
                proposal.won = True
                deal.advance(Stage.WON)
                deal.amount = proposal.amount
                won += 1
                revenue += proposal.amount
                customer = self.success.onboard(opp, deal)
                self.crm.save_customer(customer)
                self._emit("billing.invoice_created", cid, workflow_id=workflow_id,
                           payload={"opportunity_id": opp.id, "proposal_id": proposal.id},
                           metrics={"amount": proposal.amount})
                self._emit("billing.payment_succeeded", cid, workflow_id=workflow_id,
                           payload={"opportunity_id": opp.id, "proposal_id": proposal.id},
                           metrics={"amount": proposal.amount})
                self._emit("deal.won", cid, workflow_id=workflow_id,
                           payload={"opportunity_id": opp.id, "deal_id": deal.id,
                                    "proposal_id": proposal.id},
                           metrics={"amount": proposal.amount})
                self._emit("revenue.collected", cid, workflow_id=workflow_id,
                           payload={"opportunity_id": opp.id, "deal_id": deal.id},
                           metrics={"amount": proposal.amount})
                interactions.append(
                    Interaction(
                        step="close", outcome="positive", agent=self.coach.agent,
                        value=proposal.amount, **base_interaction
                    )
                )
            else:
                proposal.won = False
                deal.advance(Stage.LOST)
                self._emit("deal.lost", cid, workflow_id=workflow_id,
                           payload={"opportunity_id": opp.id, "deal_id": deal.id,
                                    "proposal_id": proposal.id})
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

        result = DayResult(
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
        self._emit(
            "workflow.completed", workflow_id, workflow_id=workflow_id,
            metrics={"discovered": result.discovered, "qualified": result.qualified,
                     "contacted": contacted, "replied": replied, "meetings": meetings,
                     "proposals": proposals, "won": won, "revenue": result.revenue},
        )
        return result

    def run_days(self, days: int, prospects: int = 50) -> list[DayResult]:
        return [self.run_day(prospects) for _ in range(days)]
