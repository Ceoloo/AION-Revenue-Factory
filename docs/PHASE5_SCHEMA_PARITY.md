# Phase 5 — Schema Parity Matrix (Revenue OS ↔ live `revenue_*`)

**Evidence:** read-only inspection of production Supabase project
`qbahthzqvxytfgobgtxa` on 2026-08-22 (`information_schema.columns`,
`table_constraints`, `pg_policies`, edge-function source, `pg_proc`). No writes.

## 1. Canonical model confirmed against the decision ledger

`aion_architecture_decisions` (authority 100) — no conflict with repo governance:

| decision_key | canonical | legacy/rejected | policy |
| --- | --- | --- | --- |
| `P0-A-REVENUE-001` | `revenue_*` = commercial system of record | `opportunities; deals; offers; proposals; customers; …; Airtable` | new revenue workflows write `revenue_*` only; Airtable downstream |
| `P0-E-DOMAIN-001` | `revenue_leads`=Leads · `revenue_deals/proposals/discovery_calls/activities`=Sales · `revenue_contacts`=CRM · `revenue_outcomes`=Revenue · `revenue_events/revenue_sync_events`=Event/Outbox | same legacy set | **no new tables**; Delivery deferred |

Repo docs (`DOMAIN_OWNERSHIP`, `DATA_OWNERSHIP`, ADR-0002/0004) already state
exactly this. **Governance reconciliation: consistent — no doc-vs-ledger conflict.**

## 2. Structural facts (live DDL)

- Every `revenue_*` table has: `id uuid PK default gen_random_uuid()`, a **text
  business key** that is `UNIQUE`, `raw_metadata jsonb NOT NULL default '{}'`,
  `source_system text NOT NULL default 'airtable_revenue_crm'`,
  `created_at/updated_at timestamptz NOT NULL default now()`.
- **Foreign keys reference the text business keys, not the uuid `id`**
  (`revenue_deals.lead_id → revenue_leads.lead_id`, etc.). Parents must exist
  first.
- **RLS is enabled on every table.** `revenue_sync_events`, `opportunities`,
  `deals` have **0 policies (default-deny)**; `revenue_leads` has 1, most
  children have 2. ⇒ canonical writes must go through a `SECURITY DEFINER` RPC /
  service-role edge function — **never an embedded service-role key** in the
  Python adapter.
- **`revenue_leads` has no version column.** Legacy `opportunities` has
  `canonical_version`; the canonical leads table does not. Optimistic
  concurrency at the row level is therefore **not yet supported for
  `revenue_*`** (cutover blocker B-2).

## 3. Field-by-field parity — projection contract vs live schema

Legend: ✅ matches · ⚠️ corrected in Phase 5 · ❌ was wrong in Phase 4 (reference
sink only, never inserted, so never surfaced).

### revenue_leads (79 cols; app-required NOT NULL: `universal_record_id`, `lead_id`)
| projection field | live column | verdict |
| --- | --- | --- |
| `universal_record_id=rf::<opp.id>` | `universal_record_id` NOT NULL UNIQUE | ❌→⚠️ **was missing**; now set |
| `lead_id=opp.id` | `lead_id` NOT NULL UNIQUE | ✅ |
| `source_record_id=opp.id` | `source_record_id` (nullable) | ✅ (column exists on *leads*) |
| `company`,`full_name`,`email`,`role`,`website`,`industry`,`country` | same | ✅ |
| `lead_score` (numeric) | `lead_score numeric` | ✅ |
| `buying_intent=str(...)` | `buying_intent text` | ✅ |
| `suggested_price` | `suggested_price numeric` | ✅ |
| `status="New"` | `status text default 'New'` | ✅ |
| `raw_metadata` | `raw_metadata jsonb` | ✅ |

### revenue_deals (app-required: `deal_id`, `deal_name`)
| projection field | live column | verdict |
| --- | --- | --- |
| `deal_name="Deal for <lead>"` | `deal_name` **NOT NULL** | ❌→⚠️ **was missing**; now set |
| `source_record_id` | *(no such column)* | ❌→⚠️ **removed** (would have errored) |
| `deal_id`,`lead_id`,`deal_stage`,`deal_value`,`agent_status`,`raw_metadata` | same | ✅ |

### revenue_discovery_calls (app-required: `discovery_call_id`, `call_name`)
| `call_name="Discovery call for <lead>"` | `call_name` **NOT NULL** | ❌→⚠️ **was missing**; now set |
| `call_date=scheduled_for.isoformat()` | `call_date date` | ✅ (fixed in Phase 4 hotfix) |
| `discovery_call_id`,`lead_id`,`call_status`,`raw_metadata` | same | ✅ |

### revenue_proposals (app-required: `proposal_id`, `proposal_name`)
| `proposal_name="Proposal <id>"` | `proposal_name` **NOT NULL** | ❌→⚠️ **was missing**; now set |
| `proposal_id`,`lead_id`,`proposal_value`,`proposal_status`,`close_probability`,`raw_metadata` | same | ✅ |

### revenue_activities (app-required: `activity_id`, `activity_name`)
| outreach row `activity_name=subject` | `activity_name` NOT NULL | ✅ |
| **interaction** row `activity_name` | `activity_name` NOT NULL | ❌→⚠️ **was missing** on the `record_interaction` path; now set |
| `activity_id`,`lead_id`,`activity_type`,`outcome`,`activity_date`,`raw_metadata` | same | ✅ |

### revenue_outcomes (app-required: `outcome_id`) — ✅ all fields match
### revenue_events (app-required: `revenue_event_id`, `revenue_event`) — ✅ all fields match

### revenue_sync_events (outbox — app-required NOT NULL)
`entity_type, entity_id, source_system, event_type, payload, previous_version,
new_version, actor_type, actor_id, supabase_record_id, idempotency_key`
(+ `idempotency_key` UNIQUE; `sync_status` default `pending`). The production
bridge builds every one of these (see `production_bridge.py`).

## 4. ID / timestamp / provenance / lifecycle parity

| concern | live behavior | adapter behavior |
| --- | --- | --- |
| surrogate `id` | DB `gen_random_uuid()` | **DB-owned** — adapter never sends it |
| business key | app-supplied UNIQUE text | RF domain id (`opp_/deal_/…`) |
| `created_at/updated_at` | DB `now()` | **DB-owned** — adapter never sends them |
| provenance | `source_system` | forced `aion_revenue_factory` (≠ default `airtable_revenue_crm`) |
| lifecycle | `status`/`*_stage` text | mapped from domain `Stage` |
| version | `revenue_sync_events.new/previous_version` (bigint NOT NULL); **no row column on `revenue_*`** | bridge supplies monotonic version; **row-level column is a cutover blocker** |
| outbox idempotency | `idempotency_key` UNIQUE NOT NULL | deterministic `sha256`-based key |

## 5. Type / nullability summary

All corrected mismatches were **NOT-NULL-without-default omissions** (4) and one
**non-existent column** (`revenue_deals.source_record_id`). No type conflicts
remain: numerics→numeric, text→text, dates serialized as `YYYY-MM-DD`, jsonb via
`raw_metadata`. `validate_canonical_row()` now fails CI if any projected row
omits a required column or targets a non-canonical table.
