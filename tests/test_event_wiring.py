from aion_revenue_factory import RevenueFactory
from aion_revenue_factory.integrations import CollectingSink
from aion_revenue_factory.integrations.aion_events import (
    has_unmasked_sensitive,
    validate_event,
)


def test_emissions_do_not_change_results():
    """The default NullSink means emission is a no-op; adding a sink must not
    change the deterministic offline results."""
    base = RevenueFactory().run_days(3, prospects=40)
    sink = CollectingSink()
    with_sink = RevenueFactory(event_sink=sink).run_days(3, prospects=40)
    assert [r.revenue for r in base] == [r.revenue for r in with_sink]
    assert [r.won for r in base] == [r.won for r in with_sink]
    assert sink.events  # events were actually emitted


def test_emitted_events_are_valid_and_threaded():
    sink = CollectingSink()
    result = RevenueFactory(event_sink=sink).run_day(prospects=50)
    types = sink.types()
    assert types.count("workflow.started") == 1
    assert types.count("workflow.completed") == 1
    assert types.count("lead.discovered") == result.discovered
    assert types.count("lead.qualified") == result.qualified
    # every emitted event conforms to the contract
    for ev in sink.events:
        assert validate_event(ev) == []
    # correlation threading: each billing event shares a correlation id with a
    # lead.discovered event (the same opportunity journey)
    discovered_corr = {e.correlation_id for e in sink.events if e.event_type == "lead.discovered"}
    billing = [e for e in sink.events if e.event_type.startswith("billing.")]
    for e in billing:
        assert e.correlation_id in discovered_corr


def test_no_unmasked_pii_in_emitted_events():
    sink = CollectingSink()
    RevenueFactory(event_sink=sink).run_day(prospects=50)
    for ev in sink.events:
        assert not has_unmasked_sensitive(ev.payload)


def test_workflow_completed_carries_outcome_metrics():
    sink = CollectingSink()
    result = RevenueFactory(event_sink=sink).run_day(prospects=50)
    completed = [e for e in sink.events if e.event_type == "workflow.completed"]
    assert len(completed) == 1
    m = completed[0].metrics
    assert m["discovered"] == result.discovered
    assert m["won"] == result.won
    assert m["revenue"] == result.revenue
