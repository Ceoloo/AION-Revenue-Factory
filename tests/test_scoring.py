from aion_revenue_factory.domain import Contact, Opportunity
from aion_revenue_factory.scoring import qualify, score_opportunity


def _opp(**signals):
    return Opportunity(
        name="Acme",
        industry="SaaS",
        kind="business",
        employees=40,
        contact=Contact("Sam Lee", "CEO", "sam@acme.com", confidence=80.0),
        signals=signals,
    )


def test_scores_are_bounded():
    s = score_opportunity(_opp(hiring=True, recent_funding=True))
    for value in (s.revenue_score, s.urgency_score, s.buying_intent, s.contact_confidence):
        assert 0.0 <= value <= 100.0
    assert s.estimated_contract_value > 0


def test_demand_signals_increase_intent_and_value():
    cold = score_opportunity(_opp())
    hot = score_opportunity(_opp(hiring=True, recent_funding=True, evaluating_vendors=True))
    assert hot.buying_intent > cold.buying_intent
    assert hot.urgency_score > cold.urgency_score
    # recent funding applies a 1.5x value multiplier
    assert hot.estimated_contract_value > cold.estimated_contract_value


def test_contact_confidence_flows_through():
    no_contact = Opportunity(name="A", industry="SaaS", employees=10)
    s = score_opportunity(no_contact)
    assert s.contact_confidence == 0.0


def test_composite_and_qualify_gate():
    hot = _opp(hiring=True, recent_funding=True)
    cold = Opportunity(name="Tiny", industry="SaaS", kind="creator", employees=1)
    cold.scores = score_opportunity(cold)
    hot.scores = score_opportunity(hot)
    assert hot.scores.composite > cold.scores.composite
    assert qualify(hot)
    assert not qualify(cold, min_composite=90.0)
