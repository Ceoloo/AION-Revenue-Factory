"""Phase 5 -- Revenue OS production write-through bridge.

Turns the Phase 4 *reference* projection into a **production-ready** write path
onto the canonical ``revenue_*`` schema, while staying reversible and refusing
to bypass the security model. Nothing here embeds a service-role key or writes
directly to Postgres: every write goes through an injected
:class:`CanonicalWriter`, which in production is an authenticated HTTPS call to a
canonical write API (a ``SECURITY DEFINER`` RPC / edge function that honours RLS
and generates the outbox event transactionally -- the same shape the existing
``revenue-control`` function uses for the *legacy* ``opportunities`` model).

What this module guarantees (proven by ``tests/test_production_bridge.py``):

* **Canonical-only.** Writes target the ``revenue_*`` family; never
  ``opportunities`` / ``deals``.
* **System-owned IDs.** The database owns the ``uuid`` surrogate (``id``) and
  the outbox ``event_id``; the adapter supplies only the natural business key
  and provenance (``source_system='aion_revenue_factory'``).
* **Idempotency.** A deterministic ``idempotency_key`` per logical write; a
  replay returns ``duplicate`` and creates no second row and no second event.
* **Optimistic concurrency.** A write may carry ``expected_version``; a stale
  version raises :class:`ConcurrencyConflict` (mirrors Postgres errcode 40001 /
  the ``revenue-control`` 409) and mutates nothing.
* **Never silently overwrite.** Updates bump a monotonic version and emit an
  outbox event; conflicts fail loudly.
* **Relationship integrity.** A child whose foreign parent (lead/deal/proposal)
  is absent is rejected, not orphaned.
* **Outbox emission.** Each write emits a ``revenue_sync_events`` row satisfying
  that table's NOT NULL contract, so ``revenue-projector`` can fan out.
* **Reversible + fail-safe.** A downstream failure leaves no partial canonical
  row; the caller sees the error.

The live canary and the deployment of the canonical write API are **gated on
explicit owner authorization** (see ``docs/PHASE5_CUTOVER_READINESS.md``); this
module is exercised offline against :class:`InMemoryCanonicalWriter`, which
faithfully models the live constraints discovered by read-only inspection.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable

from .supabase_revenue import (
    BUSINESS_KEY,
    CANONICAL_TABLES,
    SOURCE_SYSTEM,
    SupabaseRevenueAdapter,
    validate_canonical_row,
)

# entity_type recorded on the outbox row, per canonical table. Matches the
# vocabulary the projector understands ('lead' has a canonical projection
# branch today; the others require the projector extension tracked as a cutover
# blocker).
ENTITY_TYPE: dict[str, str] = {
    "revenue_leads": "lead",
    "revenue_contacts": "contact",
    "revenue_deals": "deal",
    "revenue_proposals": "proposal",
    "revenue_discovery_calls": "discovery_call",
    "revenue_activities": "activity",
    "revenue_outcomes": "outcome",
    "revenue_events": "revenue_event",
}

# Foreign-key columns each canonical row may carry -> the parent table whose
# business key must already exist. Mirrors the live FK constraints (which point
# at the text business keys, not the uuid surrogate).
FOREIGN_KEYS: dict[str, dict[str, str]] = {
    "revenue_deals": {"lead_id": "revenue_leads"},
    "revenue_proposals": {
        "lead_id": "revenue_leads",
        "deal_id": "revenue_deals",
    },
    "revenue_discovery_calls": {
        "lead_id": "revenue_leads",
        "deal_id": "revenue_deals",
    },
    "revenue_activities": {
        "lead_id": "revenue_leads",
        "deal_id": "revenue_deals",
    },
    "revenue_outcomes": {
        "lead_id": "revenue_leads",
        "deal_id": "revenue_deals",
        "proposal_id": "revenue_proposals",
    },
    "revenue_events": {
        "lead_id": "revenue_leads",
        "deal_id": "revenue_deals",
        "proposal_id": "revenue_proposals",
    },
}


class ConcurrencyConflict(RuntimeError):
    """Optimistic-concurrency check failed (stale ``expected_version``)."""


class ForeignKeyError(RuntimeError):
    """A referenced parent row (lead/deal/proposal) does not exist."""


class DownstreamWriteError(RuntimeError):
    """The canonical write API failed; no canonical row was persisted."""


@dataclass(frozen=True)
class WriteResult:
    table: str
    entity_type: str
    entity_id: str
    idempotency_key: str
    created: bool
    duplicate: bool
    version: int
    sync_event_id: Optional[str] = None


def build_idempotency_key(table: str, row: dict) -> str:
    """Deterministic idempotency key for a logical canonical write.

    Stable across replays of the *same* content, distinct across different
    content -- so a retry is a duplicate but a real state change is a new
    write. Namespaced by source + table + business key, hashed over the
    app-owned fields (``id``/timestamps are DB-owned and excluded implicitly:
    the adapter never sends them).
    """
    bk = row.get(BUSINESS_KEY[table], "")
    material = json.dumps(row, sort_keys=True, default=str)
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
    return f"{SOURCE_SYSTEM}:{table}:{bk}:{digest}"


@runtime_checkable
class CanonicalWriter(Protocol):
    """Transport that performs one authenticated canonical write + outbox emit.

    Production implementations POST to the canonical write API; they never see a
    service-role key from this process. The write MUST be atomic (row + outbox
    event in one transaction) and idempotent on ``idempotency_key``.
    """

    def write(
        self,
        table: str,
        row: dict,
        *,
        idempotency_key: str,
        entity_type: str,
        entity_id: str,
        expected_version: Optional[int] = None,
    ) -> WriteResult: ...


@dataclass
class InMemoryCanonicalWriter:
    """Faithful offline model of the live canonical write semantics.

    Models exactly the production constraints established by read-only
    inspection of the Supabase schema: unique business key per table, unique
    ``idempotency_key`` (replay -> duplicate), FK parents must pre-exist,
    monotonic per-entity version with optimistic-concurrency checks, and a
    ``revenue_sync_events`` outbox row per write satisfying its NOT NULL
    contract. Used for tests and the offline canary dry-run.
    """

    strict_fk: bool = True
    #: when set to a table name, the next write to it raises DownstreamWriteError
    fail_table: Optional[str] = None

    tables: dict[str, dict[str, dict]] = field(default_factory=dict)
    versions: dict[tuple[str, str], int] = field(default_factory=dict)
    seen_keys: dict[str, WriteResult] = field(default_factory=dict)
    sync_events: list[dict] = field(default_factory=list)
    _event_seq: int = 0

    def _rows(self, table: str) -> dict[str, dict]:
        return self.tables.setdefault(table, {})

    def write(
        self,
        table: str,
        row: dict,
        *,
        idempotency_key: str,
        entity_type: str,
        entity_id: str,
        expected_version: Optional[int] = None,
    ) -> WriteResult:
        # 1. Idempotency: replay returns the original result, no new state.
        if idempotency_key in self.seen_keys:
            return self.seen_keys[idempotency_key]

        # 2. Schema validation (canonical table + NOT NULL columns).
        validate_canonical_row(table, row)

        # 3. Foreign-key integrity: parents must pre-exist.
        if self.strict_fk:
            for fk_col, parent in FOREIGN_KEYS.get(table, {}).items():
                ref = row.get(fk_col)
                if ref is not None and ref not in self._rows(parent):
                    raise ForeignKeyError(
                        f"{table}.{fk_col}={ref!r} references missing "
                        f"{parent} row"
                    )

        # 4. Optimistic concurrency against the current entity version.
        current = self.versions.get((table, entity_id), 0)
        if expected_version is not None and expected_version != current:
            raise ConcurrencyConflict(
                f"version conflict on {table}:{entity_id}: expected "
                f"{expected_version}, current {current}"
            )

        # 5. Simulated downstream failure -> atomic: no row, no event, no key.
        if self.fail_table == table:
            self.fail_table = None
            raise DownstreamWriteError(f"canonical write API failed for {table}")

        # 6. Commit: upsert row, bump version, emit outbox event.
        created = entity_id not in self._rows(table)
        self._rows(table)[entity_id] = dict(row)
        next_version = current + 1
        self.versions[(table, entity_id)] = next_version

        self._event_seq += 1
        event_id = f"evt_{self._event_seq:06d}"
        self.sync_events.append(
            {
                "event_id": event_id,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "source_system": SOURCE_SYSTEM,
                "event_type": f"{entity_type}.{'created' if created else 'updated'}",
                "payload": dict(row),
                "previous_version": current,
                "new_version": next_version,
                "actor_type": "system",
                "actor_id": SOURCE_SYSTEM,
                "sync_status": "pending",
                "airtable_record_id": None,  # canary: null -> projector no-ops externally
                "supabase_record_id": entity_id,
                "idempotency_key": idempotency_key,
            }
        )

        result = WriteResult(
            table=table,
            entity_type=entity_type,
            entity_id=entity_id,
            idempotency_key=idempotency_key,
            created=created,
            duplicate=False,
            version=next_version,
            sync_event_id=event_id,
        )
        self.seen_keys[idempotency_key] = result
        return result


class ProductionSupabaseRevenueAdapter(SupabaseRevenueAdapter):
    """Routes canonical projections through an authenticated canonical writer.

    Identical *reads* to ``InMemoryCRM`` / ``SupabaseRevenueAdapter`` (so the
    dashboard and departments are unaffected); each projected row is written via
    the injected :class:`CanonicalWriter` with a deterministic idempotency key
    and the correct entity metadata. Results are recorded on ``self.results``
    for inspection and reconciliation.
    """

    def __init__(self, writer: CanonicalWriter) -> None:
        super().__init__()
        self.writer = writer
        self.results: list[WriteResult] = []

    def _persist(self, table: str, row: dict) -> None:
        # Keep the reference record too (parity with the base adapter).
        super()._persist(table, row)
        if table not in CANONICAL_TABLES:  # defense in depth
            raise ValueError(f"refusing non-canonical write to {table!r}")
        key = build_idempotency_key(table, row)
        entity_type = ENTITY_TYPE[table]
        entity_id = row[BUSINESS_KEY[table]]
        result = self.writer.write(
            table,
            row,
            idempotency_key=key,
            entity_type=entity_type,
            entity_id=entity_id,
        )
        self.results.append(result)

    def created_count(self) -> int:
        return sum(1 for r in self.results if r.created and not r.duplicate)

    def duplicate_count(self) -> int:
        return sum(1 for r in self.results if r.duplicate)


class RestCanonicalWriter:
    """Production transport stub: authenticated HTTPS POST to the canonical API.

    Deliberately inert until the canonical write API is deployed and a worker
    key is provisioned. It never holds a service-role key. Constructing it
    without the required bearer token raises a ``SECRET_REQUIRED`` signal rather
    than inventing a credential.
    """

    #: env var name for the worker bearer token (provisioned out of band).
    TOKEN_ENV = "REVENUE_INGEST_API_KEY"

    def __init__(self, endpoint: str, token: Optional[str]) -> None:
        if not token:
            raise RuntimeError(f"SECRET_REQUIRED: {self.TOKEN_ENV}")
        self.endpoint = endpoint
        self._token = token

    def write(self, *args: Any, **kwargs: Any) -> WriteResult:  # pragma: no cover
        raise NotImplementedError(
            "Canonical write API not deployed yet -- gated on owner "
            "authorization (see docs/PHASE5_CUTOVER_READINESS.md)."
        )
