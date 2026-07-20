"""The Agent Governance Ledger -- the enforcement layer.

This is the single decision point that stands between an AION worker and any
tool call or spend. It answers one question -- *is this agent allowed to do
this right now?* -- and returns :class:`Decision.ALLOW`, ``DENY``, or
``ESCALATE``. It is an *enforcement* layer, not merely a reporting layer:

* it verifies the agent's **identity** exists and is ``ACTIVE``;
* it fails closed on an **expired credential**;
* it blocks tools outside the agent's **approved tool** grant;
* it caps spend at the agent's **maximum spending authority** (per window);
* it routes risky-but-permitted actions to human approval per the agent's
  **escalation conditions**;
* and it writes every verdict -- allow, deny, or escalate -- into the
  tamper-evident **action history**.

The ledger records the outcome of *authorization*. Executing the side effect
is still the caller's job; after doing so the caller should call
:meth:`record_execution` so the action history is complete.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from .models import (
    AgentIdentity,
    AgentStatus,
    AuthorizationResult,
    ActionRecord,
    Credential,
    Decision,
    EscalationPolicy,
    SpendingAuthority,
    SpendPeriod,
)
from .store import LedgerStore, InMemoryLedgerStore

# Sink signature: (event_type, record) -> None
EventSink = Callable[[str, ActionRecord], None]


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


class GovernanceError(Exception):
    """Raised on illegal ledger operations (e.g. acting on a revoked agent)."""


class GovernanceLedger:
    def __init__(
        self,
        store: Optional[LedgerStore] = None,
        event_sink: Optional[EventSink] = None,
    ) -> None:
        self.store = store or InMemoryLedgerStore()
        self._sink = event_sink

    # -- registration & lifecycle -----------------------------------------
    def register_agent(
        self,
        name: str,
        objective: str,
        *,
        owner: str = "aion",
        approved_tools: Optional[set[str]] = None,
        spending: Optional[SpendingAuthority] = None,
        escalation: Optional[EscalationPolicy] = None,
        credential_secret: Optional[str] = None,
        credential_ttl_seconds: Optional[int] = None,
        activate: bool = True,
        metadata: Optional[dict] = None,
    ) -> AgentIdentity:
        """Provision a new, uniquely-identified governed agent.

        A defined ``objective`` and a ``spending`` authority are mandatory in
        spirit -- an agent with no objective or an unbounded spend is exactly
        the posture this ledger exists to prevent -- so both are set to safe,
        explicit defaults (empty tool grant, zero spend) when omitted.
        """
        agent = AgentIdentity(
            name=name,
            objective=objective,
            owner=owner,
            approved_tools=set(approved_tools or set()),
            spending=spending or SpendingAuthority(limit=0.0),
            escalation=escalation or EscalationPolicy(),
            metadata=metadata or {},
        )
        if credential_secret is not None:
            agent.credential = self._new_credential(
                credential_secret, credential_ttl_seconds
            )
        if activate:
            agent.status = AgentStatus.ACTIVE
        self.store.save_agent(agent)
        self._record(agent.agent_id, "agent.registered", Decision.ALLOW,
                     reason="provisioned",
                     context={"objective": objective, "owner": owner})
        return agent

    def _new_credential(
        self, secret: str, ttl_seconds: Optional[int], version: int = 1,
        rotated_from: Optional[str] = None,
    ) -> Credential:
        expires_at = None
        if ttl_seconds is not None:
            expires_at = (_now_dt() + timedelta(seconds=ttl_seconds)).isoformat()
        return Credential(
            fingerprint=Credential.fingerprint_of(secret),
            expires_at=expires_at,
            version=version,
            rotated_from=rotated_from,
        )

    def get_agent(self, agent_id: str) -> Optional[AgentIdentity]:
        return self.store.get_agent(agent_id)

    def _require_agent(self, agent_id: str) -> AgentIdentity:
        agent = self.store.get_agent(agent_id)
        if agent is None:
            raise GovernanceError(f"unknown agent: {agent_id}")
        return agent

    def suspend_agent(self, agent_id: str, reason: str = "") -> AgentIdentity:
        agent = self._require_agent(agent_id)
        if agent.status is AgentStatus.REVOKED:
            raise GovernanceError("cannot suspend a revoked agent")
        agent.status = AgentStatus.SUSPENDED
        agent.touch()
        self.store.save_agent(agent)
        self._record(agent_id, "agent.suspended", Decision.DENY, reason=reason)
        return agent

    def reactivate_agent(self, agent_id: str) -> AgentIdentity:
        agent = self._require_agent(agent_id)
        if agent.status is AgentStatus.REVOKED:
            raise GovernanceError("cannot reactivate a revoked agent")
        agent.status = AgentStatus.ACTIVE
        agent.touch()
        self.store.save_agent(agent)
        self._record(agent_id, "agent.reactivated", Decision.ALLOW)
        return agent

    def revoke_agent(self, agent_id: str, reason: str = "") -> AgentIdentity:
        """Permanently and irreversibly disable an agent identity."""
        agent = self._require_agent(agent_id)
        agent.status = AgentStatus.REVOKED
        agent.touch()
        self.store.save_agent(agent)
        self._record(agent_id, "agent.revoked", Decision.DENY, reason=reason)
        return agent

    # -- grants & authority mutations -------------------------------------
    def grant_tool(self, agent_id: str, tool: str) -> AgentIdentity:
        agent = self._require_agent(agent_id)
        agent.approved_tools.add(tool)
        agent.touch()
        self.store.save_agent(agent)
        self._record(agent_id, "tool.granted", Decision.ALLOW, context={"tool": tool})
        return agent

    def revoke_tool(self, agent_id: str, tool: str) -> AgentIdentity:
        agent = self._require_agent(agent_id)
        agent.approved_tools.discard(tool)
        agent.touch()
        self.store.save_agent(agent)
        self._record(agent_id, "tool.revoked", Decision.DENY, context={"tool": tool})
        return agent

    def set_spending_authority(
        self, agent_id: str, authority: SpendingAuthority
    ) -> AgentIdentity:
        agent = self._require_agent(agent_id)
        agent.spending = authority
        agent.touch()
        self.store.save_agent(agent)
        self._record(agent_id, "spend.authority_set", Decision.ALLOW,
                     context={"limit": authority.limit, "period": authority.period.value})
        return agent

    def rotate_credential(
        self, agent_id: str, secret: str, ttl_seconds: Optional[int] = None
    ) -> AgentIdentity:
        """Issue a fresh credential, superseding the current one."""
        agent = self._require_agent(agent_id)
        prior_fp = agent.credential.fingerprint if agent.credential else None
        prior_ver = agent.credential.version if agent.credential else 0
        agent.credential = self._new_credential(
            secret, ttl_seconds, version=prior_ver + 1, rotated_from=prior_fp
        )
        agent.touch()
        self.store.save_agent(agent)
        self._record(agent_id, "credential.rotated", Decision.ALLOW,
                     context={"version": agent.credential.version})
        return agent

    # -- the enforcement gate ---------------------------------------------
    def authorize(
        self,
        agent_id: str,
        tool: str,
        *,
        amount: float = 0.0,
        credential_secret: Optional[str] = None,
        context: Optional[dict] = None,
        correlation_id: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> AuthorizationResult:
        """Decide whether ``agent_id`` may invoke ``tool`` (optionally spending
        ``amount``) right now, and record the verdict.

        On :class:`Decision.ALLOW` with a positive ``amount`` the spend is
        committed against the agent's window. ``DENY`` and ``ESCALATE`` never
        commit spend. Every call appends exactly one action-history entry.
        """
        now = now or _now_dt()
        ctx = dict(context or {})
        ctx["tool"] = tool

        agent = self.store.get_agent(agent_id)
        if agent is None:
            return self._verdict(agent_id, tool, amount, Decision.DENY,
                                 "unknown_agent", None, ctx, correlation_id)

        # 1. identity status
        if agent.status is not AgentStatus.ACTIVE:
            return self._verdict(agent_id, tool, amount, Decision.DENY,
                                 f"agent_{agent.status.value}", agent, ctx, correlation_id)

        # 2. credential validity / expiration
        if agent.credential is not None:
            if credential_secret is not None:
                presented = Credential.fingerprint_of(credential_secret)
                if presented != agent.credential.fingerprint:
                    return self._verdict(agent_id, tool, amount, Decision.DENY,
                                         "credential_mismatch", agent, ctx, correlation_id)
            if agent.credential.is_expired(now):
                return self._verdict(agent_id, tool, amount, Decision.DENY,
                                     "credential_expired", agent, ctx, correlation_id)

        # 3. approved tools
        if not agent.can_use_tool(tool):
            return self._verdict(agent_id, tool, amount, Decision.DENY,
                                 "tool_not_approved", agent, ctx, correlation_id)

        # 4. escalation: sensitive tool always needs a human
        if tool in agent.escalation.sensitive_tools:
            return self._verdict(agent_id, tool, amount, Decision.ESCALATE,
                                 "sensitive_tool_requires_approval", agent, ctx, correlation_id)

        # 5. spending authority
        if amount and amount > 0:
            if not agent.spending.can_afford(amount, now):
                return self._verdict(agent_id, tool, amount, Decision.DENY,
                                     "spend_limit_exceeded", agent, ctx, correlation_id)
            threshold = agent.escalation.require_human_approval_above
            if threshold is not None and amount > threshold:
                return self._verdict(agent_id, tool, amount, Decision.ESCALATE,
                                     "spend_requires_approval", agent, ctx, correlation_id)

        # 6. allowed -- commit spend and record
        if amount and amount > 0:
            agent.spending.charge(amount, now)
            agent.touch()
            self.store.save_agent(agent)
        return self._verdict(agent_id, tool, amount, Decision.ALLOW,
                             "authorized", agent, ctx, correlation_id)

    def _verdict(
        self, agent_id: str, tool: str, amount: float, decision: Decision,
        reason: str, agent: Optional[AgentIdentity], ctx: dict,
        correlation_id: Optional[str],
    ) -> AuthorizationResult:
        remaining = agent.spending.remaining() if agent else None
        currency = agent.spending.currency if agent else "USD"
        record = self._record(agent_id, tool, decision, reason=reason,
                              amount=amount, currency=currency, context=ctx,
                              correlation_id=correlation_id)
        return AuthorizationResult(
            decision=decision,
            reason=reason,
            agent_id=agent_id,
            action=tool,
            amount=amount,
            remaining_authority=remaining,
            record_id=record.record_id,
        )

    # -- post-execution history -------------------------------------------
    def record_execution(
        self,
        agent_id: str,
        tool: str,
        *,
        amount: float = 0.0,
        outcome: Optional[dict] = None,
        correlation_id: Optional[str] = None,
    ) -> ActionRecord:
        """Append the actual executed side-effect to the action history.

        Call this after the caller has performed the tool call that a prior
        :meth:`authorize` allowed, so the ledger reflects what really happened
        and not only what was permitted.
        """
        agent = self.store.get_agent(agent_id)
        currency = agent.spending.currency if agent else "USD"
        ctx = {"tool": tool, "executed": True, **(outcome or {})}
        return self._record(agent_id, f"{tool}.executed", Decision.ALLOW,
                            reason="executed", amount=amount, currency=currency,
                            context=ctx, correlation_id=correlation_id)

    # -- history & integrity ----------------------------------------------
    def history(self, agent_id: Optional[str] = None) -> list[ActionRecord]:
        return list(self.store.list_records(agent_id))

    def verify_integrity(self) -> bool:
        """Verify the full action-history hash chain end to end.

        Returns False if any entry was altered, reordered, or removed after
        being sealed -- the property that makes this an audit ledger.
        """
        prev = "0" * 64
        for record in self.store.list_records():
            if record.prev_hash != prev:
                return False
            if not record.verify():
                return False
            prev = record.entry_hash
        return True

    # -- internals --------------------------------------------------------
    def _record(
        self, agent_id: str, action: str, decision: Decision, *,
        reason: str = "", amount: float = 0.0, currency: str = "USD",
        context: Optional[dict] = None, correlation_id: Optional[str] = None,
    ) -> ActionRecord:
        record = ActionRecord(
            agent_id=agent_id,
            action=action,
            decision=decision,
            reason=reason,
            amount=amount,
            currency=currency,
            context=context or {},
            correlation_id=correlation_id,
            prev_hash=self.store.last_hash(),
        ).seal()
        self.store.append_record(record)
        self._emit(f"governance.{decision.value}", record)
        return record

    def _emit(self, event_type: str, record: ActionRecord) -> None:
        if self._sink is None:
            return
        try:
            self._sink(event_type, record)
        except Exception:
            # Telemetry must never break enforcement.
            pass
