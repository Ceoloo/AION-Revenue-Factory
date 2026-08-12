# 12 — Unresolved Dependencies

Per the evidence standard: when evidence is insufficient, the item is `UNRESOLVED`
and never guessed. Each entry states exactly what evidence would resolve it.

| ID | Unresolved item | Why unresolved | Evidence needed to resolve |
| --- | --- | --- | --- |
| U-1 | Edge Functions / SQL / workflows in `aion-company-os` | Repo not cloned; out of session scope | Run P0-D sweep in a session scoped to `Ceoloo/aion-company-os` (private) |
| U-2 | Edge Functions / SQL / workflows in `AION-VPS-Empire-Command.V1` | Repo not cloned; out of session scope | Sweep `Ceoloo/AION-VPS-Empire-Command.V1` (private) |
| U-3 | Edge Functions / SQL / workflows in `AION-Advisor-Growth-Engine` | Repo not cloned; out of session scope | Sweep `Ceoloo/AION-Advisor-Growth-Engine` (public) |
| U-4 | Existence/definition of EVENTS legacy tables (`aion_events*`, `operational_events`, `memory_events`, `event_memory.events`, `revenue_sync_events`) | Zero references in the scanned repo | Repo sweeps (U-1..U-3) + Supabase `list_tables` |
| U-5 | Existence/definition of MEMORY legacy tables (`aion_memories`, `learning_lessons`, `aion_lessons`, LEEP, `founder_memory`, `learning_feedback`) | Zero references in the scanned repo | Repo sweeps + Supabase `list_tables` |
| U-6 | Registry/trace tables (`aion_system_registry*`, `aion_producer_consumer_trace`, `aion_repository_edge_trace`) | Zero references | Supabase `list_tables`; repo sweeps |
| U-7 | Server-side SQL functions, triggers, views, RLS policies | Repo defines none; server not inspected | Supabase read-only introspection (`list_migrations`, `list_tables`, `get_advisors`) |
| U-8 | `pg_cron` / scheduled functions / DB webhooks | None in-repo; server not inspected | Supabase `list_extensions` (is `pg_cron`/`pg_net` on?) + schedule/webhook enumeration |
| U-9 | External **readers** of `opportunities/deals/offers/messages/meetings/proposals/customers/interactions` | This repo reads none from backend | Downstream consumer discovery (BI, other repos, Airtable automations, dashboards) |
| U-10 | Whether Supabase is the org **source of truth** or a projection | Repo treats its local cache as read-truth; backend is a write mirror | Architecture confirmation + reader map (U-9) |
| U-11 | Whether **other systems also write** the 8 revenue tables (multiple-writer risk) | Only this repo's writer is visible | Repo sweeps (U-1..U-3) + Supabase write-source audit / logs |
| U-12 | `SUPABASE_KEY` type per deployment (anon vs service-role) | Key supplied at runtime; not in repo | Deployment/env inventory (names only; never expose values) |
| U-13 | Actual production table names (via `tables=` override) | Overridable constructor arg | Deployment wiring / config inspection |
| U-14 | Prospect API response schema + endpoint identity | `map_record` injected per deployment (prospect_sources.py:66) | Deployment config; the concrete `map_record` used |
| U-15 | Canonical routing of `interactions` (REVENUE vs EVENTS) | Event-shaped rows written to a CRM table; no event bus in-repo | Canonical architecture decision + EVENTS store owner (U-4) |
| U-16 | Durable Founder Memory / Learning Loop target | Only in-memory `KnowledgeBase` exists here | MEMORY canonical binding (U-5) + owner repo |

## Migration classification status (all sources)

Per §13 rules, with "when uncertain choose UNRESOLVED":

| Source | Migration class | Reason |
| --- | --- | --- |
| `opportunities`, `deals`, `offers`, `messages`, `meetings`, `proposals`, `customers`, `interactions` | **UNRESOLVED** | Writers understood within this repo, but **readers unknown** (U-9) and cross-system writers unconfirmed (U-11). Cannot certify REDIRECT/MIGRATE/DUAL-READ/READ-ONLY/RETIRE. |
| EVENTS legacy family | **UNRESOLVED** | Not present in scanned repo (U-4). |
| MEMORY legacy family | **UNRESOLVED** | Not present in scanned repo (U-5). |
| Registry/trace tables | **UNRESOLVED** | Not present (U-6). |
| `KnowledgeBase` (in-memory) | **UNRESOLVED** | No durable footprint to classify (U-16). |

**Nothing in this repository qualifies for REDIRECT_NOW, MIGRATE, DUAL_READ,
READ_ONLY, or RETIRE on current evidence.** All are UNRESOLVED pending U-1..U-16.
