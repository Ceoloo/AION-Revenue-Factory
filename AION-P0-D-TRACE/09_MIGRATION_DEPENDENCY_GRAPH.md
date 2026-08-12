# 09 — Migration Dependency Graph

Repository: **Ceoloo/AION-Revenue-Factory**

## Primary dependency chain (machine-readable form in `migration_graph.json`)

```
[TRIGGER] manual run_day / run_days            cli.py:88-95 ; orchestrator.py:236-237
   ↓
[COMPONENT] RevenueFactory (orchestrator)      orchestrator.py:73-234
   ↓
[FUNCTION] discovery/offers/outreach/... + CRM write-through methods
   ↓
[EXTERNAL IN] HTTP prospect API  ──▶ opportunities   prospect_sources.py:101 ; orchestrator.py:130
[EXTERNAL IN] Claude (Anthropic) ──▶ offers/messages/proposals copy   anthropic_gateway.py:56
   ↓
[DATABASE OBJECT] public.{opportunities,deals,offers,messages,meetings,proposals,customers,interactions}
                  (INSERT via write_through.py:157-187 ; supabase_crm.py:50-69 / airtable_crm.py:41-63)
   ↓
[WORKFLOW] (none server-side — no pg_cron / no scheduled fn / no queue)
   ↓
[EXTERNAL SYSTEM OUT] Airtable OR Supabase (persist) ; SMTP/ESP (deliver messages)
   ↓
[CANONICAL TARGET] REVENUE
```

Parallel copy path:

```
Claude ─▶ offer/outreach/proposal text ─▶ offers/messages/proposals ─▶ REVENUE
prospect API ─▶ opportunities ─▶ REVENUE
messages ─▶ SmtpSender/WebhookSender ─▶ SMTP / ESP / dialer / voice-AI
```

## Structural findings

| Pattern | Present? | Detail / evidence |
| --- | --- | --- |
| **PARALLEL PATHS** | ⚠️ Yes (config-time) | Two interchangeable CRM sinks — `AirtableCRM` vs `SupabaseCRM` — for the *same* 8 objects. Only one active per deployment (`config.py:41-50`), but the same data can land in different backends across environments. |
| **DUPLICATE SOURCES** | ⚠️ Yes (latent) | Airtable and Supabase are schema-identical mirrors (backend-agnostic `_*_fields`, write_through.py:27-128). Cross-environment duplication risk. |
| **MULTIPLE WRITERS** | ❌ Not within this repo | Exactly one writer path (`WriteThroughCRM`). Whether *other* AION systems also write these tables: **UNRESOLVED** (cutover blocker if true). |
| **MULTIPLE READERS** | ❓ UNRESOLVED | This repo reads none of the tables from the backend. External readers unknown. |
| **CIRCULAR DEPENDENCIES** | ❌ No | Module deps point strictly downward (domain ← integrations ← departments ← orchestrator; ARCHITECTURE.md:22-26). No import cycles. |
| **LEGACY → LEGACY CHAINS** | ❌ None observed | No event/memory legacy tables referenced. |
| **CANONICAL → LEGACY WRITES** | ❌ None observed | No writes from a canonical store back to a legacy one (no such code). |
| **LEGACY → CANONICAL BRIDGES** | ❌ None in-repo | No bridge/ETL code. `interactions` is the only latent bridge candidate (event-shaped rows in a revenue table) — see `08_CANONICAL_MAPPING.md`. |
| **HIDDEN READERS / BACKGROUND JOBS** | ❓ UNRESOLVED | None in this repo; server-side (`pg_cron`, DB webhooks) and other repos not inspected. |

## Cutover-relevant graph facts

1. This repo is a **pure producer** into the REVENUE object group. Retiring or
   redirecting it affects **writes**, not reads.
2. The **read side is invisible** from here — the biggest graph gap. No redirect can
   be certified without mapping who reads `opportunities/deals/...` downstream.
3. The **EVENTS and MEMORY canonical branches are entirely absent** from this repo's
   graph — they must be reconstructed from the unscanned repos + the Supabase project.
