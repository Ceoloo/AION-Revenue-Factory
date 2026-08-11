from aion_revenue_factory.outreach import (
    AIPersonalizer,
    InMemoryOutreachStore,
    OutreachDashboard,
)
from aion_revenue_factory.integrations import TemplateGateway

from .conftest import IN_WINDOW


def test_personalizer_structured_output(campaign, lead):
    store = InMemoryOutreachStore()
    p = AIPersonalizer(TemplateGateway(), store)
    result = p.personalize(lead, campaign, campaign.steps[0])
    assert result.subject
    assert result.body
    assert 0.0 <= result.confidence <= 1.0
    assert result.rationale
    # generation is stored for audit
    assert len(store.generations()) == 1


def test_confidence_higher_with_more_facts(campaign):
    from aion_revenue_factory.outreach import Lead

    store = InMemoryOutreachStore()
    p = AIPersonalizer(TemplateGateway(), store)
    thin = Lead(email="a@x.example", company="Acme")
    rich = Lead(email="b@x.example", company="Acme", industry="Electrical Contracting",
                job_title="Owner", website="acme.example")
    c_thin = p.personalize(thin, campaign, campaign.steps[0]).confidence
    c_rich = p.personalize(rich, campaign, campaign.steps[0]).confidence
    assert c_rich > c_thin


def test_ai_disabled_uses_template_verbatim(campaign, lead):
    store = InMemoryOutreachStore()
    step = campaign.steps[0]
    step.ai_personalization = False
    p = AIPersonalizer(TemplateGateway(), store)
    result = p.personalize(lead, campaign, step)
    assert result.subject == step.subject
    assert result.body == step.body_template
    assert result.confidence == 1.0


def test_metrics_and_roi(system, campaign, lead):
    system.engine.create_campaign(campaign)
    system.engine.add_lead(campaign, lead)
    system.engine.activate(campaign)
    system.engine.enqueue_due(campaign, now=IN_WINDOW)
    system.worker.process_once(now=IN_WINDOW)
    system.engine.mark_reply(campaign.id, lead.id, positive=True)
    system.engine.mark_converted(campaign.id, lead.id, revenue=5000.0)

    dash = OutreachDashboard(system.store, cost_per_email=0.001, cost_per_generation=0.01)
    m = dash.campaign_metrics(campaign)
    assert m["emails_sent"] == 1
    assert m["revenue"] == 5000.0
    assert m["positive_replies"] == 1
    assert m["converted"] == 1
    assert m["revenue_per_email"] == 5000.0
    # ROI is a real number here (there is cost + revenue)
    assert isinstance(m["roi"], float)
    assert m["roi"] > 0


def test_roi_no_cost_sentinel():
    from aion_revenue_factory.outreach import Campaign

    store = InMemoryOutreachStore()
    campaign = Campaign(name="zero cost")
    store.save_campaign(campaign)
    dash = OutreachDashboard(store, cost_per_email=0.0, cost_per_generation=0.0)
    m = dash.campaign_metrics(campaign)
    assert m["roi"] == "Not enough cost data"
