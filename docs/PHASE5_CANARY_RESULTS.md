# Phase 5 — Live Canary Results (AUTH-1 + AUTH-3)

**Authorized by the owner** (AUTH-1..3). Executed against production Supabase
`qbahthzqvxytfgobgtxa` on 2026-08-22. Synthetic data only, clearly labeled
`[P5 SYNTHETIC - SAFE TO DELETE]`, `airtable_record_id=null` (so `revenue-projector`
no-ops externally). No customer or real record touched. Rows torn down after
verification; the RPC is left deployed.

## Pre-flight (read-only)
- **No triggers** on `revenue_leads` or `revenue_sync_events` → a lead insert has
  no hidden side effects (no auto-projection, no cascade).
- Canary keys free; target function absent.

## AUTH-1 — deployed
`public.apply_revenue_lead_upsert(...)` — additive `SECURITY DEFINER` RPC, locked
`search_path`, writes only `revenue_leads` + `revenue_sync_events`. Version-
controlled at `supabase/migrations/20260822000000_apply_revenue_lead_upsert.sql`.
Reversible via `DROP FUNCTION public.apply_revenue_lead_upsert(jsonb,text,text,text,bigint);`.

## AUTH-3 — first canary sequence (single lead)

| step | call | result | proves |
| --- | --- | --- | --- |
| create | key `p5-canary-k1` | `duplicate=false, new_version=1`, row + `lead.created` event | write path |
| replay | key `p5-canary-k1` again | `duplicate=true, new_version=1`, **no new row/event** (same `event_id`) | idempotency |
| conflict | key `p5-canary-k2-stale`, `expected_version=0` | **error 40001** “version conflict: expected 0, current 1”, nothing written | optimistic concurrency |
| update | key `p5-canary-k2-update`, `expected_version=1` | `duplicate=false, new_version=2`, **same** `supabase_id` + `lead.updated` event | update + no duplication |

Torn down (2 events + 1 lead deleted, 0 residue).

## AUTH-3 — formal run (expanded, two synthetic leads)

Baseline before run: legacy `opportunities=20`, `deals=20`.

| # | verification point | step | live result |
| --- | --- | --- | --- |
| 1 | successful creation | lead A, key `p5-a-create` | `duplicate=false, v1`, `lead.created` event, DB uuid assigned |
| 2 | idempotent replay | lead A, key `p5-a-create` again | `duplicate=true, v1`, same `event_id`, no new row/event |
| 3 | duplicate protection | (same as #2) | outbox `idempotency_key` UNIQUE enforced; one event only |
| 4 | invalid input rejection | lead B, missing `universal_record_id` | **P0001** “lead_id and universal_record_id are required”, nothing written |
| 5 | concurrency behavior | lead A, `expected_version=0` (current 1) | **40001** conflict, nothing written |
| 6 | failure behavior | (the #4 failure) | no partial row, no event, idempotency key **not** consumed |
| 7 | retry behavior | lead B, same key `p5-b-invalid-then-retry`, corrected row | succeeds `v1` — retry-safe |
| 8 | no legacy writes | post-run counts | `opportunities=20`, `deals=20` (unchanged); 0 synthetic refs in legacy |
| 9 | no external Airtable mutation | outbox inspection | 3/3 events `airtable_record_id=null`; projector `lead` branch no-ops externally by source |
| 10 | audit/event integrity | outbox inspection | correct `previous/new_version`, distinct `idempotency_key`, `actor_id`, `supabase_record_id` per event |

### Verified end state (before teardown)
- **2** `revenue_leads`: `rf-p5-canary-a` (`status=Qualified`, website updated),
  `rf-p5-canary-b` (`status=New`); both `source_system='aion_revenue_factory'`,
  `airtable_record_id=null`.
- **3** `revenue_sync_events`: A `(0→1 created)`, A `(1→2 updated)`,
  B `(0→1 created)` — all `entity_type='lead'`, `pending`, `airtable_record_id=null`.

### Teardown
3 events + 2 leads deleted → **0 residue**. Legacy `opportunities=20`, `deals=20`
unchanged. Production pristine; RPC retained.

## AUTH-2 — STOPPED (reported, not forced)
- **Secret provisioning:** no available tool sets a Supabase edge-function secret,
  and a secret must not be fabricated/printed → `SECRET_REQUIRED: REVENUE_INGEST_API_KEY`
  (owner sets it via Supabase dashboard/CLI).
- **Edge-fn deploy withheld:** there is no `delete_edge_function` tool, so deploying
  `revenue-lead-write` could not be guaranteed reversible → tripped the
  “rollback cannot be guaranteed” stop condition. Source is committed and ready;
  the owner deploys it alongside setting the secret.
- **Unauthenticated fail-closed** is guaranteed by construction: the function
  returns 503 when the secret is unset and 401 on a bad bearer — no write path
  without a valid worker token.

## Still gated (post-AUTH-3 — require new authorization)
- **AUTH-2 completion** (owner sets secret; deploy `revenue-lead-write`).
- **B-3** projector canonical branches for deal/proposal/outcome.
- **AUTH-4** optional `revenue_*` row version column.
- **AUTH-5** migrate/retire legacy-targeting `revenue-control`; then freeze
  `opportunities`/`deals`.
- Real-data (non-synthetic) parity + production wiring of RF → edge fn.
