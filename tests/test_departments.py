import random

from aion_revenue_factory.departments import (
    CustomerSuccess,
    DealCoach,
    MeetingPrep,
    OfferIntelligence,
    OpportunityDiscovery,
    OutreachWorkforce,
    ProposalGenerator,
    SyntheticSource,
)
from aion_revenue_factory.domain import Channel, Contact, Deal, Opportunity, Stage
from aion_revenue_factory.integrations import KnowledgeBase, TemplateGateway
from aion_revenue_factory.scoring import score_opportunity


def _hot_opp():
    opp = Opportunity(
        name="Acme", industry="SaaS", kind="business", employees=120,
        contact=Contact("Sam", "CEO", "s@a.com", 85.0),
        signals={"hiring": True, "recent_funding": True, "website_tech_gap": True},
    )
    opp.scores = score_opportunity(opp)
    return opp


def test_discovery_scores_and_ranks():
    disc = OpportunityDiscovery(SyntheticSource(seed=1))
    opps = disc.discover(20)
    assert len(opps) == 20
    assert all(o.scores.estimated_contract_value > 0 for o in opps)
    ranked = disc.rank(opps)
    composites = [o.scores.composite for o in ranked]
    assert composites == sorted(composites, reverse=True)


def test_offer_intelligence_prices_from_value():
    opp = _hot_opp()
    dept = OfferIntelligence(TemplateGateway(), KnowledgeBase(), rng=random.Random(0), epsilon=0.0)
    offer = dept.create_offer(opp)
    assert offer.price >= 1_500
    assert offer.roi_estimate > offer.price  # positive ROI
    assert offer.assets


def test_outreach_composes_and_sends():
    sent = []
    dept = OutreachWorkforce(
        TemplateGateway(), KnowledgeBase(), send=lambda m: sent.append(m) or "sent",
        rng=random.Random(0),
    )
    opp = _hot_opp()
    offer = OfferIntelligence(TemplateGateway(), KnowledgeBase(), rng=random.Random(0)).create_offer(opp)
    channel = dept.choose_channel(opp)
    assert isinstance(channel, Channel)
    msg = dept.compose(opp, offer, channel)
    dept.send(msg)
    assert msg.status == "sent"
    assert msg.sent_at is not None
    assert len(sent) == 1


def test_meeting_prep_builds_briefing():
    opp = _hot_opp()
    offer = OfferIntelligence(TemplateGateway(), KnowledgeBase(), rng=random.Random(0)).create_offer(opp)
    meeting = MeetingPrep().prepare(opp, offer)
    assert meeting.prep["pain_points"]
    assert meeting.prep["objections"]
    assert meeting.prep["pricing_recommendation"]["list_price"] == offer.price


def test_deal_coach_probability_bounds_and_recs():
    opp = _hot_opp()
    kb = KnowledgeBase()
    offer = OfferIntelligence(TemplateGateway(), kb, rng=random.Random(0)).create_offer(opp)
    coach = DealCoach(kb)
    prob = coach.close_probability(opp, offer)
    assert 0.0 <= prob <= 1.0
    proposal = ProposalGenerator(TemplateGateway()).generate(opp, offer)
    recs = coach.recommend(opp, offer, proposal)
    assert "objection_handling" in recs and "strategy" in recs


def test_customer_success_onboards():
    opp = _hot_opp()
    deal = Deal(opportunity_id=opp.id, amount=24_000)
    deal.advance(Stage.WON)
    customer = CustomerSuccess().onboard(opp, deal)
    assert customer.mrr == 2_000  # 24000 / 12
    assert customer.onboarding_tasks
    assert 0.0 <= customer.health_score <= 100.0
