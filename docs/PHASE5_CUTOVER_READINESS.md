# Phase 5 — Cutover Readiness Report

**Deployment boundary (objective 18):** code written ✅ · tests passing ✅ ·
deployed ❌ · production canary ❌ · production cutover ❌. CI-green is **not**
production-ready.

## A. Can Revenue Factory safely write to production Supabase?
**Not yet — by one missing component.** The projection contract now matches the
live DDL, and the adapter enforces idempotency, optimistic concurrency, FK
integrity, canonical-only writes, and outbox emission (all tested). But RLS is
default-deny on the outbox, so a write must land through a `SECURITY DEFINER`
canonical write API that **does not yet exist** (B-1). Once deployed, the offline
proofs transfer directly.

## B. Which API/function should own those writes?
A **new minimal canonical write RPC** (`apply_revenue_upsert`), modeled on the
proven `revenue-control` shape but targeting `revenue_*`. **Not** the existing
`revenue-control` — it writes legacy `opportunities`/`deals`. (Full rationale:
`PHASE5_PRODUCTION_BRIDGE.md` §2.)

## C. Is `revenue_sync_events` correctly positioned?
**Yes.** It is the outbox `revenue-projector` already consumes. Its NOT NULL
contract (idempotency_key UNIQUE, previous/new_version, actor, supabase_record_id)
is exactly what the bridge emits. The projector’s `entity_type='lead'` branch is
canonical and — with `airtable_record_id=null` — no-ops externally, giving a safe
canary. **Do not redesign it** (objective 13).

## D. Are all canonical relationships preserved?
**Yes, and enforced.** FKs reference the text business keys; the bridge writes
parents before children (orchestrator order) and rejects a child whose parent is
absent (`ForeignKeyError`, tested). `universal_record_id` (previously missing) is
now always set.

## E. Is idempotency proven?
**Yes (offline).** Deterministic `sha256` idempotency key; replay ⇒ duplicate,
no second row, no second event (`test_full_run_projects_and_is_replay_idempotent`,
`test_duplicate_idempotency_key_is_a_noop_duplicate`). DB-level uniqueness on
`revenue_sync_events.idempotency_key` backs it in production.

## F. Is rollback proven?
**Yes (offline) + reversible by construction.** Downstream failure leaves no
partial row/event and does not consume the idempotency key, so retry is safe
(`test_downstream_failure_leaves_no_partial_row`). The whole bridge is additive:
reverting the commit removes it; the base `SupabaseRevenueAdapter` and
`InMemoryCRM` paths are untouched. No production state is created to roll back yet.

## G. Can legacy `opportunities`/`deals` now be frozen?
**No — not yet.** Three things must hold first: (1) canonical write API live and
canaried (B-1); (2) `revenue-projector` extended to project canonical
deal/proposal/outcome entity types, or confirmation those need no external
projection (B-3); (3) the deployed `revenue-control` still writes legacy — it must
be migrated or retired **before** freeze, or live writers would break. Freeze is a
later, explicitly-authorized cutover phase (per `DEPRECATION_POLICY.md`).

## H. What remains before production cutover?
1. **B-1** Build + deploy the canonical write RPC/edge function (owner-authorized).
2. **B-2** Add row-level version support for `revenue_*` (a `canonical_version`
   column or version-from-outbox) — leads have none today; needed for true
   row-level optimistic concurrency.
3. **B-3** Extend `revenue-projector` for canonical non-lead entity types (or
   confirm no external projection needed).
4. **Canary** synthetic leads end-to-end (airtable_record_id=null), then teardown.
5. **Parity on real data** RF-written canonical rows vs InMemoryCRM vs live state.
6. **Migrate/retire** the legacy-targeting `revenue-control` write path.

## I. What must the owner authorize before proceeding?
- **AUTH-1** Deploy the new canonical write API to production Supabase (DDL +
  edge function).
- **AUTH-2** Provision a worker bearer token (`SECRET_REQUIRED: REVENUE_INGEST_API_KEY`)
  — never a service-role key in the app.
- **AUTH-3** Execute the live synthetic canary (writes to production
  `revenue_leads` + `revenue_sync_events`).
- **AUTH-4** (later) Add the `revenue_*` version column (schema change).
- **AUTH-5** (later) Migrate/retire `revenue-control`; freeze `opportunities`/`deals`.

Standing invariant: no production data, schema, service, or traffic has been
changed in Phase 5. All work is additive, CI-green, and reversible.

## Open item flagged for the owner (not a doc-vs-ledger conflict)
The **deployed** `revenue-control` + `apply_revenue_control_command` write the
**legacy** `opportunities`/`deals`, which contradicts the canonical decision
(`P0-A-REVENUE-001`) that `revenue_*` is the system of record. This is a
*runtime/system* divergence, not a repository-vs-ledger documentation conflict
(repo docs and the ledger agree). Resolving it is AUTH-5 above.
