# 03 — Supabase Dependency Trace (Producer / Consumer)

Repository: **Ceoloo/AION-Revenue-Factory**

## Summary

- Supabase is reached **only** as a CRM persistence backend via **PostgREST HTTP
  `POST`** — i.e. **INSERT / write-through only**.
- **8 Supabase table names** are referenced (all lowercase in the Supabase adapter).
- The repo is a **PRODUCER** to every one of these tables. It performs **NO reads,
  NO RPC, NO PostgREST `GET/PATCH/DELETE`, NO SQL** against Supabase — dashboard
  reads are served from the in-process `InMemoryCRM` cache, never from Supabase.
- **NONE** of the canonical legacy sources (`events`, `aion_events`,
  `aion_events_v2`, `operational_events`, `memory_events`, `event_memory.events`,
  `revenue_sync_events`, `aion_memories`, `learning_lessons`, `aion_lessons`, LEEP,
  `founder_memory`, `learning_feedback`, `aion_system_registry*`) are referenced
  anywhere. Confirmed absent by full-text search.

## The write path (evidence chain)

```
run_day()  (orchestrator.py:122-234)
   ↓ calls crm.upsert_opportunity / save_offer / save_message / save_meeting /
     save_proposal / upsert_deal / save_customer / record_interaction
WriteThroughCRM.<method>  (write_through.py:157-187)
   ↓ super().<method>()  → local cache      (fast dashboard reads)
   ↓ self._persist(self.tables[<entity>], <fields dict>)
SupabaseCRM._persist(table, record)  (supabase_crm.py:50-69)
   ↓ POST {SUPABASE_URL}/rest/v1/{table}   headers: apikey, Authorization: Bearer,
     Prefer: return=minimal
Supabase table (INSERT)
```

## Table name resolution

`WriteThroughCRM.DEFAULT_TABLES` (write_through.py:138-147) maps logical entities to
capitalized names; `SupabaseCRM` overrides them to lowercase via `_LOWER_TABLES`
(supabase_crm.py:21-31):

| Logical entity | Supabase table | Airtable table (default) |
| --- | --- | --- |
| opportunities | `opportunities` | `Opportunities` |
| deals | `deals` | `Deals` |
| offers | `offers` | `Offers` |
| messages | `messages` | `Messages` |
| meetings | `meetings` | `Meetings` |
| proposals | `proposals` | `Proposals` |
| customers | `customers` | `Customers` |
| interactions | `interactions` | `Interactions` |

Operators may remap any of these via the `tables=` constructor arg
(`supabase_crm.py:38,44`) — so real table names are deployment-dependent.

## Producer / Consumer table (evidence-backed)

Format: SOURCE → ACTION → TARGET → EVIDENCE → CLASSIFICATION.

| SOURCE (component) | ACTION | TARGET (`public.<table>`) | EVIDENCE | ROLE |
| --- | --- | --- | --- | --- |
| `SupabaseCRM.upsert_opportunity` → `_persist` | WRITES (INSERT) | `opportunities` | write_through.py:157-159; supabase_crm.py:50-63; row shape `_opportunity_fields` write_through.py:27-45 | PRODUCER |
| `SupabaseCRM.upsert_deal` → `_persist` | WRITES (INSERT) | `deals` | write_through.py:161-163; `_deal_fields` 48-60 | PRODUCER |
| `SupabaseCRM.save_offer` → `_persist` | WRITES (INSERT) | `offers` | write_through.py:165-167; `_offer_fields` 63-72 | PRODUCER |
| `SupabaseCRM.save_message` → `_persist` | WRITES (INSERT) | `messages` | write_through.py:169-171; `_message_fields` 75-84 | PRODUCER |
| `SupabaseCRM.save_meeting` → `_persist` | WRITES (INSERT) | `meetings` | write_through.py:173-175; `_meeting_fields` 87-92 | PRODUCER |
| `SupabaseCRM.save_proposal` → `_persist` | WRITES (INSERT) | `proposals` | write_through.py:177-179; `_proposal_fields` 95-103 | PRODUCER |
| `SupabaseCRM.save_customer` → `_persist` | WRITES (INSERT) | `customers` | write_through.py:181-183; `_customer_fields` 106-114 | PRODUCER |
| `SupabaseCRM.record_interaction` → `_persist` | WRITES (INSERT) | `interactions` | write_through.py:185-187; `_interaction_fields` 117-128 | PRODUCER |

Confirming test: `tests/test_live_integrations.py:127-143` asserts
`POST https://x.supabase.co/rest/v1/opportunities` with header `apikey` and row
`{"name":"Acme",...}` — **HIGH confidence, direct write evidence.**

### Reads from Supabase

**NONE.** The dashboard reads exclusively from the local cache:
`Dashboard.metrics()` iterates `crm.deals()` / `crm.won_deals()` which return
in-memory dicts (`integrations/crm.py:77-85`). No component issues a Supabase
`GET`. Consequence: this repo cannot detect rows written by any *other* system —
it is a blind producer.

## Non-Supabase Supabase-relevant references

- `supabase-js` import: **absent** (Python repo; uses stdlib `urllib`).
- PostgREST endpoint literal: `f"{self.base_url}/rest/v1/{table}"` (supabase_crm.py:51).
- RPC (`/rest/v1/rpc/...`): **absent.**
- Database webhooks / triggers configured from this repo: **absent.**
- `pg_cron`: **absent.**

## Machine-readable rows

See `supabase_dependency_trace.json`.
