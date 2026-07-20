"""Data models for the Agent Governance Ledger.

Every AION worker is a first-class, individually-governed identity rather than
a share of one broad service account. An :class:`AgentIdentity` carries the
seven properties the governance model requires:

1. a unique identity        -> ``agent_id``
2. a defined objective      -> ``objective``
3. approved tools           -> ``approved_tools``
4. maximum spending authority -> ``spending`` (:class:`SpendingAuthority`)
5. credential expiration     -> ``credential`` (:class:`Credential`)
6. escalation conditions     -> ``escalation`` (:class:`EscalationPolicy`)
7. complete action history   -> the append-only, hash-chained ledger of
                                :class:`ActionRecord` entries (see ``ledger``)

Everything here is pure-stdlib so it runs in CI without credentials.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


# Comparisons on money use cents-level tolerance so binary float noise
# (0.1 + 0.2 != 0.3) never wrongly denies or allows a spend.
_MONEY_EPSILON = 1e-9


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid() -> str:
    return str(uuid.uuid4())


def _parse(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    return datetime.fromisoformat(ts)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class AgentStatus(str, Enum):
    """Lifecycle of a governed agent identity."""

    PROVISIONED = "provisioned"  # created, not yet cleared to act
    ACTIVE = "active"            # may act within its authority
    SUSPENDED = "suspended"      # temporarily blocked (recoverable)
    REVOKED = "revoked"          # permanently disabled (terminal)


class Decision(str, Enum):
    """Outcome of an authorization check -- the enforcement verdict."""

    ALLOW = "allow"        # within authority, proceed
    DENY = "deny"          # outside authority, blocked
    ESCALATE = "escalate"  # requires human approval before proceeding


class SpendPeriod(str, Enum):
    """Window over which the spending limit is enforced."""

    PER_ACTION = "per_action"  # each single action must be <= limit
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    TOTAL = "total"            # lifetime cap, never resets


_PERIOD_SECONDS: dict[SpendPeriod, Optional[int]] = {
    SpendPeriod.DAILY: 86_400,
    SpendPeriod.WEEKLY: 604_800,
    SpendPeriod.MONTHLY: 2_592_000,  # 30d rolling window
    SpendPeriod.PER_ACTION: None,
    SpendPeriod.TOTAL: None,
}


# ---------------------------------------------------------------------------
# Credential (expiration)
# ---------------------------------------------------------------------------
@dataclass
class Credential:
    """A time-boxed credential fingerprint for an agent.

    The ledger never stores the raw secret -- only a fingerprint (a salted
    hash) plus issue/expiry timestamps. Expiry is enforced at authorization
    time, so a stale credential fails closed.
    """

    fingerprint: str
    issued_at: str = field(default_factory=_now)
    expires_at: Optional[str] = None
    version: int = 1
    rotated_from: Optional[str] = None  # fingerprint of the prior credential

    def is_expired(self, now: Optional[datetime] = None) -> bool:
        if not self.expires_at:
            return False  # non-expiring credential (discouraged, but explicit)
        now = now or datetime.now(timezone.utc)
        return now >= _parse(self.expires_at)

    def seconds_until_expiry(self, now: Optional[datetime] = None) -> Optional[float]:
        if not self.expires_at:
            return None
        now = now or datetime.now(timezone.utc)
        return (_parse(self.expires_at) - now).total_seconds()

    @staticmethod
    def fingerprint_of(secret: str, salt: str = "aion-governance") -> str:
        return hashlib.sha256(f"{salt}:{secret}".encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Spending authority (maximum spending authority)
# ---------------------------------------------------------------------------
@dataclass
class SpendingAuthority:
    """The maximum an agent may spend, and the window it is measured over."""

    limit: float
    currency: str = "USD"
    period: SpendPeriod = SpendPeriod.DAILY
    spent: float = 0.0
    window_started_at: str = field(default_factory=_now)

    def reset_if_elapsed(self, now: Optional[datetime] = None) -> bool:
        """Roll the spend window forward if its period has elapsed.

        Returns True if a reset occurred. PER_ACTION and TOTAL never reset.
        """
        seconds = _PERIOD_SECONDS.get(self.period)
        if seconds is None:
            return False
        now = now or datetime.now(timezone.utc)
        started = _parse(self.window_started_at)
        if (now - started).total_seconds() >= seconds:
            self.spent = 0.0
            self.window_started_at = now.isoformat()
            return True
        return False

    def remaining(self, now: Optional[datetime] = None) -> float:
        if self.period is SpendPeriod.PER_ACTION:
            return self.limit
        self.reset_if_elapsed(now)
        return max(0.0, self.limit - self.spent)

    def can_afford(self, amount: float, now: Optional[datetime] = None) -> bool:
        if amount <= 0:
            return True
        if self.period is SpendPeriod.PER_ACTION:
            return amount <= self.limit + _MONEY_EPSILON
        return amount <= self.remaining(now) + _MONEY_EPSILON

    def charge(self, amount: float, now: Optional[datetime] = None) -> None:
        """Commit a spend against the window. Callers must check first."""
        if amount <= 0:
            return
        if self.period is not SpendPeriod.PER_ACTION:
            self.reset_if_elapsed(now)
            self.spent += amount

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["period"] = self.period.value
        return d


# ---------------------------------------------------------------------------
# Escalation policy (escalation conditions)
# ---------------------------------------------------------------------------
@dataclass
class EscalationPolicy:
    """Conditions under which an otherwise-permitted action must instead be
    escalated to a human approver rather than executed autonomously.

    Escalation is distinct from denial: the action is *within* the agent's
    granted authority but crosses a risk threshold that requires a human in
    the loop.
    """

    # Spend at or above this amount escalates instead of auto-allowing.
    require_human_approval_above: Optional[float] = None
    # Tools that always require human approval, regardless of spend.
    sensitive_tools: set[str] = field(default_factory=set)

    def to_dict(self) -> dict[str, Any]:
        return {
            "require_human_approval_above": self.require_human_approval_above,
            "sensitive_tools": sorted(self.sensitive_tools),
        }


# ---------------------------------------------------------------------------
# Agent identity
# ---------------------------------------------------------------------------
@dataclass
class AgentIdentity:
    """A uniquely-identified, individually-governed AION worker."""

    name: str
    objective: str
    owner: str = "aion"
    agent_id: str = field(default_factory=lambda: f"agt_{_uuid()}")
    status: AgentStatus = AgentStatus.PROVISIONED
    approved_tools: set[str] = field(default_factory=set)
    spending: SpendingAuthority = field(
        default_factory=lambda: SpendingAuthority(limit=0.0)
    )
    credential: Optional[Credential] = None
    escalation: EscalationPolicy = field(default_factory=EscalationPolicy)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def touch(self) -> None:
        self.updated_at = _now()

    def can_use_tool(self, tool: str) -> bool:
        # A single "*" grant means the agent is trusted with any tool. This is
        # discouraged and is exactly the broad-service-account posture the
        # ledger exists to replace, but it is explicit and audited.
        return "*" in self.approved_tools or tool in self.approved_tools

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "objective": self.objective,
            "owner": self.owner,
            "status": self.status.value,
            "approved_tools": sorted(self.approved_tools),
            "spending": self.spending.to_dict(),
            "credential": self.credential.to_dict() if self.credential else None,
            "escalation": self.escalation.to_dict(),
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @staticmethod
    def from_dict(obj: dict[str, Any]) -> "AgentIdentity":
        spend = obj.get("spending") or {}
        cred = obj.get("credential")
        esc = obj.get("escalation") or {}
        return AgentIdentity(
            name=obj["name"],
            objective=obj["objective"],
            owner=obj.get("owner", "aion"),
            agent_id=obj["agent_id"],
            status=AgentStatus(obj.get("status", "provisioned")),
            approved_tools=set(obj.get("approved_tools", [])),
            spending=SpendingAuthority(
                limit=spend.get("limit", 0.0),
                currency=spend.get("currency", "USD"),
                period=SpendPeriod(spend.get("period", "daily")),
                spent=spend.get("spent", 0.0),
                window_started_at=spend.get("window_started_at", _now()),
            ),
            credential=Credential(**cred) if cred else None,
            escalation=EscalationPolicy(
                require_human_approval_above=esc.get("require_human_approval_above"),
                sensitive_tools=set(esc.get("sensitive_tools", [])),
            ),
            metadata=obj.get("metadata", {}),
            created_at=obj.get("created_at", _now()),
            updated_at=obj.get("updated_at", _now()),
        )


# ---------------------------------------------------------------------------
# Action history (complete action history -- hash-chained ledger entry)
# ---------------------------------------------------------------------------
@dataclass
class ActionRecord:
    """One tamper-evident entry in the agent action history.

    Records are chained: each entry's ``entry_hash`` is computed over its own
    canonical contents plus the previous entry's hash. Any retroactive edit
    breaks the chain and is detectable via
    :meth:`GovernanceLedger.verify_integrity`. This is what makes the ledger
    an *enforcement/audit* record and not merely a log.
    """

    agent_id: str
    action: str                       # tool / operation attempted
    decision: Decision                # the enforcement verdict recorded
    reason: str = ""                  # machine-readable reason code
    amount: float = 0.0
    currency: str = "USD"
    context: dict[str, Any] = field(default_factory=dict)
    correlation_id: Optional[str] = None
    record_id: str = field(default_factory=lambda: f"act_{_uuid()}")
    timestamp: str = field(default_factory=_now)
    prev_hash: str = "0" * 64
    entry_hash: str = ""

    def _canonical(self) -> str:
        payload = {
            "record_id": self.record_id,
            "agent_id": self.agent_id,
            "action": self.action,
            "decision": self.decision.value,
            "reason": self.reason,
            "amount": round(self.amount, 6),
            "currency": self.currency,
            "context": self.context,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp,
            "prev_hash": self.prev_hash,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    def compute_hash(self) -> str:
        return hashlib.sha256(self._canonical().encode("utf-8")).hexdigest()

    def seal(self) -> "ActionRecord":
        """Finalize the entry by computing its hash. Idempotent."""
        self.entry_hash = self.compute_hash()
        return self

    def verify(self) -> bool:
        return self.entry_hash == self.compute_hash()

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["decision"] = self.decision.value
        return d

    @staticmethod
    def from_dict(obj: dict[str, Any]) -> "ActionRecord":
        return ActionRecord(
            agent_id=obj["agent_id"],
            action=obj["action"],
            decision=Decision(obj["decision"]),
            reason=obj.get("reason", ""),
            amount=obj.get("amount", 0.0),
            currency=obj.get("currency", "USD"),
            context=obj.get("context", {}),
            correlation_id=obj.get("correlation_id"),
            record_id=obj["record_id"],
            timestamp=obj["timestamp"],
            prev_hash=obj.get("prev_hash", "0" * 64),
            entry_hash=obj.get("entry_hash", ""),
        )


@dataclass
class AuthorizationResult:
    """The verdict returned by :meth:`GovernanceLedger.authorize`."""

    decision: Decision
    reason: str
    agent_id: str
    action: str
    amount: float = 0.0
    remaining_authority: Optional[float] = None
    record_id: Optional[str] = None

    @property
    def allowed(self) -> bool:
        return self.decision is Decision.ALLOW

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["decision"] = self.decision.value
        return d
