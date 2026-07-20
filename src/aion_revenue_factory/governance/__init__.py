"""Agent Governance Ledger (vendored) -- per-agent identity + enforcement.

This is a faithful, dependency-free vendored copy of
``aion_platform.governance`` (canonical source: the ``aion-company-os``
repository, ``packages/aion_platform/aion_platform/governance``). It is
vendored rather than imported so this repository stays runnable with zero
external dependencies, following the "vendored contract" pattern the platform
package documents.

Keep ``models.py``, ``store.py``, and ``ledger.py`` in sync with the canonical
package; the public contract (``GovernanceLedger.authorize`` returning
``ALLOW``/``DENY``/``ESCALATE`` and the hash-chained action history) must not
drift.

The Revenue Factory uses this as the enforcement gate in front of every AI
employee's outward dispatch -- see ``orchestrator.py``.
"""

from .models import (
    AgentIdentity,
    AgentStatus,
    Credential,
    SpendingAuthority,
    SpendPeriod,
    EscalationPolicy,
    Decision,
    ActionRecord,
    AuthorizationResult,
)
from .store import (
    LedgerStore,
    InMemoryLedgerStore,
    JsonlLedgerStore,
    GENESIS_HASH,
)
from .ledger import GovernanceLedger, GovernanceError

__all__ = [
    "AgentIdentity",
    "AgentStatus",
    "Credential",
    "SpendingAuthority",
    "SpendPeriod",
    "EscalationPolicy",
    "Decision",
    "ActionRecord",
    "AuthorizationResult",
    "LedgerStore",
    "InMemoryLedgerStore",
    "JsonlLedgerStore",
    "GENESIS_HASH",
    "GovernanceLedger",
    "GovernanceError",
]
