# 10 — Dangerous Dependencies

Repository: **Ceoloo/AION-Revenue-Factory**

Risk scale: LOW / MEDIUM / HIGH / CRITICAL. Each item has code evidence.

| # | Risk | Item | Evidence | Why it is dangerous for a migration |
| --- | --- | --- | --- | --- |
| 1 | **HIGH** | **Service-role key possible via `SUPABASE_KEY`** | supabase_crm.py:8-10, 57-59; test uses `"servicekey"` test_live_integrations.py:138 | The same env var is sent as `apikey` + `Bearer`. If an operator sets a service-role key, this writer bypasses RLS entirely. Any table remap or cutover must account for RLS-bypassing writes that won't show up in policy-scoped audits. |
| 2 | **HIGH** | **Silent write failures (data loss on outage)** | supabase_crm.py:64-69; airtable_crm.py:55-63; senders.py:110-117 | `raise_on_error` defaults **False**, so backend/webhook errors are swallowed. The local cache keeps the row but the durable backend silently misses it. During/after a migration, dropped writes would be invisible — no exception, no retry, no dead-letter. |
| 3 | **HIGH** | **No read-back / no idempotency → duplicate rows** | supabase_crm.py:50-63 (`POST` + `Prefer: return=minimal`); write_through.py (no conflict handling) | Every write is a blind INSERT with no `on_conflict`/upsert. Re-runs, retries, or dual-write windows produce duplicate rows keyed only by an app-generated `id`. Migrations that replay data will duplicate. |
| 4 | **MEDIUM** | **Hard-coded PostgREST path + endpoint shape** | supabase_crm.py:51 `f"{base_url}/rest/v1/{table}"`; airtable_crm.py:21 `_API_ROOT` | Table routing is string-built. A schema/endpoint change (e.g. moving to an RPC or a different schema) requires code changes here, not config. |
| 5 | **MEDIUM** | **Dual interchangeable CRM sinks (duplication risk)** | config.py:41-50; write_through.py:27-128 | Airtable and Supabase hold identical schemas; environment config alone decides the sink. Easy to end up with two partial sources of truth across environments. |
| 6 | **MEDIUM** | **Unknown external readers of the revenue tables** | (absence of any read in-repo: crm.py:77-85, dashboard.py) | This repo can't tell you who consumes `opportunities/deals/...`. Making them read-only or redirecting them risks breaking undiscovered consumers. |
| 7 | **MEDIUM** | **Operator-supplied table names** | supabase_crm.py:38,44; write_through.py:149-151 | `tables=` remapping means the real table names are deployment-specific; a trace built only from code defaults may not match production table names. |
| 8 | **MEDIUM** | **Outbound side effects fire during any run** | orchestrator.py:147; senders.py (SMTP send / webhook POST) | Running `run_day` with live env vars **sends real outreach** and **writes real rows**. Any "test in prod" or replay has real-world (email/dialer) consequences. Relevant when validating a migration against live config. |
| 9 | **LOW** | **Ephemeral learning state (no durability)** | knowledge.py:24-27; orchestrator.py:221 | `KnowledgeBase` is process-memory only. Not a migration hazard, but means there is no `aion_memories`/`learning_lessons` persistence to migrate from here (the memory canonical branch is simply absent). |
| 10 | **LOW** | **Lazy third-party SDK import** | anthropic_gateway.py:42-54 | `anthropic` imported at `__init__`; a missing package fails only at gateway construction. Minor operational sharp edge, not a data risk. |

## Not-present dangerous patterns (verified absent)

- No `pg_cron`, DB triggers, or scheduled functions defined in-repo (nothing to
  accidentally leave running).
- No inbound webhook consumers.
- No production HTTP API routes / server.
- No hidden background workers or queue consumers.
- No Airtable↔Supabase sync job (the two sinks never talk to each other).

## Highest-priority risks for cutover

1. **#6 Unknown external readers** — the single biggest unknown; blocks any
   redirect / read-only decision.
2. **#2 Silent write failures** — would mask data loss during a dual-write migration.
3. **#3 No idempotency** — replay/dual-write duplicates.
4. **#1 Service-role bypass** — audits scoped by RLS may under-count writes.
