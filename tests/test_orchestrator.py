from aion_revenue_factory import Dashboard, RevenueFactory
from aion_revenue_factory.domain import Stage


def test_run_day_produces_a_working_funnel():
    factory = RevenueFactory()
    result = factory.run_day(prospects=50)
    assert result.discovered == 50
    # Funnel counts strictly narrow (or stay equal) as they go deeper.
    assert result.qualified <= result.discovered
    assert result.contacted >= result.replied >= result.meetings
    assert result.meetings >= result.proposals >= result.won
    assert result.revenue >= 0


def test_multi_day_run_generates_revenue():
    factory = RevenueFactory()
    results = factory.run_days(5, prospects=50)
    assert len(results) == 5
    assert sum(r.won for r in results) > 0
    assert sum(r.revenue for r in results) > 0


def test_runs_are_deterministic():
    a = RevenueFactory().run_days(3, prospects=40)
    b = RevenueFactory().run_days(3, prospects=40)
    assert [r.revenue for r in a] == [r.revenue for r in b]
    assert [r.won for r in a] == [r.won for r in b]


def test_dashboard_metrics_are_consistent():
    factory = RevenueFactory()
    factory.run_days(5, prospects=50)
    metrics = Dashboard(factory.crm).metrics()

    assert 0.0 <= metrics["reply_rate"] <= 1.0
    assert 0.0 <= metrics["close_rate"] <= 1.0
    assert 0.0 <= metrics["proposal_win_rate"] <= 1.0
    assert metrics["arr"] == round(metrics["mrr"] * 12, 2)
    assert metrics["total_revenue"] > 0
    # every won deal is attributed to an agent and an offer
    assert metrics["revenue_by_agent"]
    assert metrics["revenue_by_offer"]


def test_learning_loop_differentiates_winners():
    factory = RevenueFactory()
    factory.run_days(7, prospects=50)
    snap = factory.knowledge.snapshot()
    assert snap["wins"] > 0
    # After a week, at least one offer type should be favored above neutral.
    assert max(snap["offer_weight"].values()) > 1.0
    # Won deals should be recorded on the CRM as customers.
    won = [d for d in factory.crm.deals() if d.stage is Stage.WON]
    assert len(factory.crm.customers) == len(won)
