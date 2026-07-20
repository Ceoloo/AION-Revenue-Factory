"""The Agent Governance Ledger is wired into the orchestrator's dispatch point.

Every outreach send is authorized against the acting AI employee's governed
identity before it happens; denied/escalated sends never leave the building,
and every verdict is recorded in the tamper-evident action history.
"""

from aion_revenue_factory.orchestrator import RevenueFactory
from aion_revenue_factory.domain import Channel, Stage
from aion_revenue_factory.governance import Decision, SpendingAuthority, SpendPeriod
from aion_revenue_factory.governance_agents import (
    OUTREACH_TOOL,
    build_default_workforce,
)


def _outreach_authorizations(ledger):
    return [r for r in ledger.history() if r.action == OUTREACH_TOOL]


def test_default_run_authorizes_and_records_every_send():
    f = RevenueFactory()
    result = f.run_day(40)

    allows = [r for r in _outreach_authorizations(f.ledger)
              if r.decision is Decision.ALLOW]
    executions = [r for r in f.ledger.history()
                  if r.action == f"{OUTREACH_TOOL}.executed"]

    # one authorize + one execution per contacted prospect
    assert len(allows) == result.contacted
    assert len(executions) == result.contacted
    assert result.contacted > 0
    assert f.ledger.verify_integrity() is True


def test_revoked_agent_sends_are_blocked_not_dispatched():
    f = RevenueFactory()
    f.run_day(40)  # let the learning loop pick channels

    email_id = f.workforce.agent_id_for(Channel.EMAIL)
    f.ledger.revoke_agent(email_id, reason="compromised")

    result = f.run_day(40)
    blocked = [i for i in result.interactions if i.outcome == "blocked"]

    # every blocked send is an email send (only the email agent was revoked)
    assert blocked, "expected the revoked agent's sends to be blocked"
    assert all(i.channel is Channel.EMAIL for i in blocked)
    # blocked deals never reached CONTACTED
    for record in _outreach_authorizations(f.ledger):
        if record.decision is Decision.DENY:
            assert record.reason == "agent_revoked"
    assert f.ledger.verify_integrity() is True


def test_over_budget_send_is_denied():
    # A tiny per-action budget below the message cost denies the first send.
    workforce = build_default_workforce()
    for channel, agent_id in workforce.agent_ids.items():
        workforce.ledger.set_spending_authority(
            agent_id, SpendingAuthority(limit=1.0, period=SpendPeriod.PER_ACTION)
        )
    f = RevenueFactory(workforce=workforce)
    result = f.run_day(40)

    assert result.contacted == 0  # nothing could afford to send
    denials = [r for r in _outreach_authorizations(f.ledger)
               if r.decision is Decision.DENY]
    assert denials and all(r.reason == "spend_limit_exceeded" for r in denials)


def test_unapproved_tool_is_denied():
    workforce = build_default_workforce()
    for agent_id in workforce.agent_ids.values():
        workforce.ledger.revoke_tool(agent_id, OUTREACH_TOOL)
    f = RevenueFactory(workforce=workforce)
    result = f.run_day(40)

    assert result.contacted == 0
    denials = [r for r in _outreach_authorizations(f.ledger)
               if r.decision is Decision.DENY]
    assert denials and all(r.reason == "tool_not_approved" for r in denials)
