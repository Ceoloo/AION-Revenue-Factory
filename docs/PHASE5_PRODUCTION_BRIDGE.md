# Phase 5 — Revenue OS Production Write Path

**Status:** design + code + tests complete and CI-green; **live canary and
canonical-write-API deployment are GATED on explicit owner authorization.**
Nothing in this phase writes to production Supabase.

## 1. The intended production flow

```
Revenue Factory domain event  (orchestrator state transition)
   ↓
ProductionSupabaseRevenueAdapter._persist(table, row)      [in this repo]
   ↓  deterministic idempotency_key + entity metadata
CanonicalWriter.write(...)   → authenticated HTTPS POST     [RestCanonicalWriter, NOT deployed]
   ↓
Canonical write API  (SECURITY DEFINER RPC / edge function) [NOT built yet — B-1]
   ↓  one transaction: upsert revenue_* row + insert revenue_sync_events
canonical revenue_* table   +   revenue_sync_events (pending)
   ↓
revenue-projector  (existing edge function, worker-scheduled)
   ↓  entity_type='lead' branch; airtable_record_id=null ⇒ mark completed, NO external write
external projection (Airtable)  — only when an airtable_record_id is present
   ↓
worker / audit telemetry
```

The adapter is a drop-in `CRM` (same reads as `InMemoryCRM`), so departments and
the dashboard are unchanged; only the write side is routed through the writer.

## 2. Decision: what should own canonical writes? (objective 6)

Three options were evaluated **against evidence**, not assumption:

| option | finding | verdict |
| --- | --- | --- |
| **A. Reuse `revenue-control`** | Its RPC `apply_revenue_control_command` writes the **legacy** `opportunities`/`deals` tables; its `ALLOWED` patch fields are legacy vocabulary (`name,stage,progress,amount,…`). It cannot write `revenue_leads` without a rewrite. | **Reject as-is** |
| **B. Wrap `revenue-control`** | Wrapping still lands in `opportunities` — a canonical write would become a legacy write. Violates P0-A-REVENUE-001. | **Reject** |
| **C. Minimal canonical write API** | A new `SECURITY DEFINER` RPC `apply_revenue_upsert(entity, business_key, patch, expected_version, idempotency_key, actor)` — **mirroring** the proven `revenue-control` shape (idempotency row-check → concurrency check → upsert → outbox insert), but targeting `revenue_*`. Smallest change that honours RLS and the canonical decision. | **Recommend — build under authorization (B-1)** |

The Python adapter is written to option C: it already emits exactly the fields
that RPC needs. **Not implemented/deployed in this phase** (the directive: “Do
NOT implement this decision until the evidence is collected”).

## 3. Security posture (objective 17)

- **No service-role key** is referenced, requested, or hardcoded anywhere in the
  adapter. RLS is default-deny on the outbox; writes go through a definer
  function reached with a **worker bearer token**, exactly like the existing
  functions (`requireWorkerKey`).
- `RestCanonicalWriter` refuses to construct without its token and reports
  `SECRET_REQUIRED: REVENUE_INGEST_API_KEY` rather than inventing one.
- Payloads carry no unmasked secrets; provenance is `source_system=aion_revenue_factory`.

## 4. Production canary strategy (objective 7) — **design only, not executed**

- **Vehicle:** synthetic leads only, every text field prefixed
  `[P5 SYNTHETIC - SAFE TO DELETE]`, `universal_record_id=rf::p5-canary-<n>`,
  `source_system=aion_revenue_factory`.
- **Isolation from Airtable:** insert the sync event with
  `airtable_record_id = null`. The projector’s `lead` branch then marks the
  event `completed` **without any Airtable PATCH** — the full DB→outbox→projector
  path is exercised with **zero external mutation**. No real customer, lead,
  deal, proposal, or Airtable record is touched.
- **Scope:** `revenue_leads` + `revenue_sync_events` only. No deals/proposals
  (their projector branch is not canonical yet — B-3).
- **Teardown:** synthetic rows are deletable by `universal_record_id` prefix;
  a teardown script is part of the authorized canary, not this phase.
- **Gate:** requires (a) the canonical write API deployed (B-1) and (b) explicit
  owner authorization to write to production. Until then the canary runs
  **offline** against `InMemoryCanonicalWriter` (see §6).

## 5. Failure-recovery matrix (objective 10) — proven in tests

| scenario | expected behavior | test |
| --- | --- | --- |
| malformed / missing required field | rejected **before** any write (`CanonicalValidationError`); no row | `test_missing_required_not_null_is_rejected_before_write` |
| non-canonical / legacy table target | rejected (`CanonicalValidationError`); adapter also refuses at `_persist` | `test_non_canonical_table_is_rejected`, `test_adapter_only_targets_canonical_tables` |
| duplicate event (same idempotency key) | no-op duplicate; **no second row, no second outbox event** | `test_duplicate_idempotency_key_is_a_noop_duplicate` |
| stale `expected_version` | `ConcurrencyConflict`; nothing mutated (mirrors PG 40001 / 409) | `test_stale_expected_version_conflicts_and_writes_nothing` |
| child before parent (FK) | `ForeignKeyError`; no orphan row | `test_child_before_parent_is_rejected_no_orphan` |
| simulated downstream failure | `DownstreamWriteError`; **no partial row, no event**; idempotency key **not** consumed ⇒ retry can succeed | `test_downstream_failure_leaves_no_partial_row` |
| projector failure | existing projector marks that `revenue_sync_events` row `failed` with `error`, leaves canonical row intact, retries on next tick (pending selection) | documented; projector behavior read from source |

## 6. Idempotency & flow proof (objectives 8, 9) — offline

`test_full_run_projects_and_is_replay_idempotent` runs the whole factory through
`ProductionSupabaseRevenueAdapter(InMemoryCanonicalWriter)`:
first pass creates canonical rows + outbox events; **replaying the identical
rows produces only duplicates — canonical row count and outbox event count are
unchanged.** `InMemoryCanonicalWriter` enforces the same invariants as the live
schema (unique business key, unique idempotency key, FK-parent-first, monotonic
version, NOT-NULL outbox), so the proof transfers to production once the write
API (B-1) is deployed.

## 7. What is deliberately NOT done (objective 13)

No production migration; no deletion of `opportunities`/`deals`/scripts; no
historical backfill; Airtable and legacy systems untouched; no VPS work; no
credential rotation; OpenClaw approval gates, `worker_runs`, `aion_events_v2`,
and `revenue_sync_events` schema all unmodified.
