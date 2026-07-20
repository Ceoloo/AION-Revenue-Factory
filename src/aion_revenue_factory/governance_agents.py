"""Provision the Revenue Factory's AI employees as governed agent identities.

Each channel-owning AI employee (see ``departments.outreach.CHANNEL_AGENTS``)
is registered in the Agent Governance Ledger with its own identity, a defined
objective, an explicit approved-tool grant, a bounded daily spending authority,
and escalation conditions. The orchestrator then calls ``ledger.authorize(...)``
before that employee dispatches any outward action.

This replaces the "everything shares one broad account" posture: every send is
attributable to a uniquely-identified agent and enforced against its authority.
"""

from __future__ import annotations

from dataclasses import dataclass

from .domain import Channel
from .departments.outreach import CHANNEL_AGENTS
from .governance import (
    GovernanceLedger,
    SpendingAuthority,
    SpendPeriod,
    EscalationPolicy,
)

# The tool an outreach employee invokes when it contacts a prospect.
OUTREACH_TOOL = "outreach.send"

# Blended cost to dispatch one outreach message (matches dashboard CAC basis).
OUTREACH_COST_PER_MESSAGE = 8.0

# Per-channel daily spend authority. Budgets are generous enough that a normal
# autonomous day runs unchanged; they exist to cap runaway spend, not throttle
# ordinary operation.
_DAILY_BUDGET = 5_000.0

# The Voice AI employee places live calls -- a higher-touch, higher-risk action,
# so spend above this per-action amount escalates to a human instead of firing
# autonomously.
_VOICE_AI_APPROVAL_ABOVE = 25.0


@dataclass
class GovernedWorkforce:
    """A ledger plus the map from an outreach channel to its governed agent id."""

    ledger: GovernanceLedger
    agent_ids: dict[Channel, str]

    def agent_id_for(self, channel: Channel) -> str:
        return self.agent_ids[channel]


def build_default_workforce(event_sink=None) -> GovernedWorkforce:
    """Provision every outreach AI employee as an active governed identity."""
    ledger = GovernanceLedger(event_sink=event_sink)
    agent_ids: dict[Channel, str] = {}
    for channel, name in CHANNEL_AGENTS.items():
        escalation = EscalationPolicy()
        if channel is Channel.VOICE_AI:
            escalation = EscalationPolicy(
                require_human_approval_above=_VOICE_AI_APPROVAL_ABOVE
            )
        agent = ledger.register_agent(
            name=name,
            objective=f"Contact and qualify prospects via {channel.value}",
            approved_tools={OUTREACH_TOOL},
            spending=SpendingAuthority(limit=_DAILY_BUDGET, period=SpendPeriod.DAILY),
            escalation=escalation,
            metadata={"channel": channel.value},
        )
        agent_ids[channel] = agent.agent_id
    return GovernedWorkforce(ledger=ledger, agent_ids=agent_ids)
