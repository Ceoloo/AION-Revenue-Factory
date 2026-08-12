# 11 — P0-D Executive Findings

Scope of this pass: **1 of 4** AION repositories (`Ceoloo/AION-Revenue-Factory`,
fully scanned). The other 3 exist but were out of this session's scope.

## Answers to the 17 required questions

1. **How many repositories were scanned?** — **1** (AION-Revenue-Factory). 3 others
   discovered but not scanned (out of session scope).
2. **How many Edge Functions?** — **0** in the scanned repo. (Platform total: UNRESOLVED — likely in the unscanned repos.)
3. **How many SQL functions?** — **0** in the scanned repo (no SQL/migrations/RPC exist here). Platform total: UNRESOLVED.
4. **How many workflows?** — **1** in-process workflow (`RevenueFactory.run_day/run_days`). Zero external schedulers/CI/queues.
5. **How many Supabase objects referenced?** — **8** tables: `opportunities, deals, offers, messages, meetings, proposals, customers, interactions`.
6. **How many legacy sources actively written?** — **8** (the revenue object group above), and only when live CRM env vars are set. **0** of the event/memory/registry legacy families are written.
7. **How many legacy sources actively read?** — **0** from any Supabase backend (dashboard reads the local cache only).
8. **Which sources have multiple writers?** — **None within this repo** (single write-through path). Cross-system multiple-writer status: **UNRESOLVED**.
9. **Which sources have multiple systems of truth?** — Latent: the same 8 objects can be mirrored to **Airtable and Supabase** (schema-identical). Within one deployment only one is active; across environments this is a duplication/SoT risk. Org-wide SoT: UNRESOLVED.
10. **Which sources can be redirected?** — **None can be certified yet** — redirect requires knowing downstream readers (Q7 shows this repo reads none). Classification `UNRESOLVED` for all.
11. **Which require migration?** — Data-transform migration for the 8 objects is **minimal** (flat field mappers already exist). But no migration should proceed without reader evidence → currently `UNRESOLVED`.
12. **Which require dual-read?** — UNRESOLVED (no reader map).
13. **Which should become read-only?** — **None yet.** This repo is a *writer*; read-only would break `run_day`. Safe only after the writer is deliberately retired.
14. **Which can eventually be retired?** — The ephemeral in-memory `KnowledgeBase` has no durable footprint to retire. No table is retirement-eligible on current evidence.
15. **What remains unresolved?** — The entire **EVENTS** and **KNOWLEDGE/MEMORY** canonical branches (absent here), all **external readers**, server-side SQL/`pg_cron`/triggers/RLS, and **3 unscanned repos**. See `12_UNRESOLVED_DEPENDENCIES.md`.
16. **Top 10 cutover blockers** — see below.
17. **What exact evidence is still missing?** — see "Missing evidence" below.

## Top 10 cutover blockers

| # | Blocker | Where | Status |
| --- | --- | --- | --- |
| 1 | 3 of 4 AION repos not scanned — EVENTS/MEMORY/edge-function surface unknown | account repos | UNRESOLVED |
| 2 | Downstream **readers** of `opportunities/deals/...` unknown | not visible in this repo | UNRESOLVED |
| 3 | Server-side Supabase objects (SQL fns, triggers, `pg_cron`, RLS) not inspected | live project | UNRESOLVED |
| 4 | Silent write failures (`raise_on_error=False`) can mask data loss | supabase_crm.py:64-69; airtable_crm.py:55-63 | CONFIRMED |
| 5 | No idempotency/upsert → replay & dual-write duplicates | supabase_crm.py:50-63 | CONFIRMED |
| 6 | Possible service-role key (RLS bypass) via `SUPABASE_KEY` | supabase_crm.py:57-59 | CONFIRMED (config-dependent) |
| 7 | Dual Airtable/Supabase sinks → duplicate systems of truth across envs | config.py:41-50 | CONFIRMED (latent) |
| 8 | Real table names are operator-configurable (`tables=`) | supabase_crm.py:38,44 | CONFIRMED |
| 9 | `interactions` is event-shaped but lands in a CRM table, not an EVENTS store | write_through.py:117-128 | CONFIRMED |
| 10 | Learning/memory state is ephemeral — no `aion_memories`/LEEP persistence to trace | knowledge.py:24-27 | CONFIRMED (absence) |

## Missing evidence (exact)

- The `supabase/functions/`, migrations, and SQL-function inventory from
  `aion-company-os`, `AION-VPS-Empire-Command.V1`, `AION-Advisor-Growth-Engine`.
- A read-only schema snapshot of the live Supabase project: `list_tables`,
  `list_migrations`, `list_extensions` (is `pg_cron`/`pg_net` enabled?),
  `get_advisors` (RLS/security), and any DB webhooks.
- The prospect API response contract (`map_record` is injected per deployment;
  prospect_sources.py:66).
- Which key type (`anon` vs `service_role`) each deployment actually sets in
  `SUPABASE_KEY`.
- The actual `tables=` overrides used in production.

---

# RECOMMENDED NEXT P0

> No deletion, no production migration, no config changes are recommended.
> The following are **evidence-gathering** steps required before any of
> REDIRECT / MIGRATE / DUAL-READ / READ-ONLY / RETIRE can be assigned to any source.

1. **P0-D-2 — Scan the other 3 AION repos** with this exact sweep (highest priority).
   They almost certainly hold the Edge Functions, SQL, `pg_cron`, and the EVENTS /
   MEMORY legacy tables that are absent here. *Requires a session scoped to each
   repo, or explicit approval to `add_repo` them into this session.*

2. **P0-D-3 — Read-only Supabase project introspection.** Run `list_tables`,
   `list_migrations`, `list_extensions`, `get_advisors`, and enumerate DB
   webhooks/triggers. This reveals the server-side objects no repo scan can show and
   confirms whether `pg_cron`/event tables exist. (Read-only MCP calls; no writes.)

3. **P0-D-4 — Reader/consumer discovery for the 8 revenue tables.** Until every
   *reader* of `opportunities/deals/...` is enumerated (BI, dashboards, other repos,
   Airtable automations), **no redirect/read-only decision is safe.**

4. **Before REDIRECT:** confirm (a) all writers (this repo + any others), (b) all
   readers, (c) that the canonical REVENUE target accepts the identical schema.

5. **Before MIGRATE:** confirm the field transform (trivial here) *and* an
   idempotent/upsert load strategy to avoid the duplicate-row risk (blocker #5).

6. **Before DUAL-READ:** map readers first (P0-D-4); dual-read is meaningless without
   knowing who reads.

7. **Before READ-ONLY:** confirm this writer is intentionally retired/redirected —
   otherwise read-only breaks `run_day`.

8. **Before RETIRE:** prove zero active writers **and** zero readers — not
   demonstrable from this repo alone.
