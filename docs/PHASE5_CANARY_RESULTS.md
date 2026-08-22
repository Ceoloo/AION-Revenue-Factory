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

## AUTH-3 — canary sequence (all against production)

| step | call | result | proves |
| --- | --- | --- | --- |
| create | key `p5-canary-k1` | `duplicate=false, new_version=1`, row + `lead.created` event | write path (obj 8) |
| replay | key `p5-canary-k1` again | `duplicate=true, new_version=1`, **no new row/event** (same `event_id`) | idempotency (obj 9) |
| conflict | key `p5-canary-k2-stale`, `expected_version=0` | **error 40001** “version conflict: expected 0, current 1”, nothing written | optimistic concurrency (obj 10) |
| update | key `p5-canary-k2-update`, `expected_version=1` | `duplicate=false, new_version=2`, **same** `supabase_id` (one row) + `lead.updated` event | update + no duplication |

### Verified end state (before teardown)
- **1** `revenue_leads` row: `status='Qualified'` (updated), `website` updated,
  `source_system='aion_revenue_factory'`, `airtable_record_id=null`,
  `raw_metadata.updated=true`. One row despite four calls.
- **2** `revenue_sync_events`: `(prev 0 → new 1, lead.created)` and
  `(prev 1 → new 2, lead.updated)`, both `entity_type='lead'`,
  `source_system='aion_revenue_factory'`, `sync_status='pending'`,
  `airtable_record_id=null` (projector completes them with **no external write**).

### Teardown
`revenue_sync_events` (2) and `revenue_leads` (1) synthetic rows deleted — **0
residue**. Production left pristine; RPC retained.

## Not done (still gated)
- **AUTH-2** provision `REVENUE_INGEST_API_KEY` (owner) — `SECRET_REQUIRED`.
- Deploy `supabase/functions/revenue-lead-write` (pairs with AUTH-2).
- **B-3** projector canonical branches for deal/proposal/outcome.
- **AUTH-5** migrate/retire legacy-targeting `revenue-control`; then freeze
  `opportunities`/`deals`.
- Real-data (non-synthetic) parity + production wiring of RF → edge fn.
