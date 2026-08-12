# 01 — Repository Inventory

**Mission:** P0-D — Edge Function + Repository Consumer Trace
**Mode:** READ-ONLY forensic extraction. No source, DB, deployment, or config was modified.
**Sweep date:** 2026-08-12
**Session scope:** GitHub access for this session is scoped to `Ceoloo/AION-Revenue-Factory` only.

---

## 0. Repository discovery result

Four AION repositories exist under the `Ceoloo` account (enumerated read-only via the
account repo listing). Only **one** was cloned into this workspace and is in this
session's scan scope.

| Repository | Visibility | Last push | Cloned locally? | Scanned this session? |
| --- | --- | --- | --- | --- |
| `Ceoloo/AION-Revenue-Factory` | public | 2026-08-11 | ✅ yes | ✅ **FULLY SCANNED** |
| `Ceoloo/AION-Advisor-Growth-Engine` | public | 2026-08-10 | ❌ no | ❌ NOT SCANNED — out of session scope |
| `Ceoloo/AION-VPS-Empire-Command.V1` | private | 2026-08-08 | ❌ no | ❌ NOT SCANNED — out of session scope |
| `Ceoloo/aion-company-os` | private | 2026-07-29 | ❌ no | ❌ NOT SCANNED — out of session scope |

> **Evidence gap (declared, not guessed):** The three unscanned repos are the most
> likely home of Supabase Edge Functions, SQL migrations, `pg_cron` jobs, and the
> canonical `aion_events*` / `aion_memories` / LEEP legacy tables — **none of which
> exist in AION-Revenue-Factory**. Their traces are marked `UNRESOLVED` throughout
> and scanning them is the #1 Recommended Next P0 (see `11_P0_D_FINDINGS.md`).

---

## 1. AION-Revenue-Factory — full inventory

| Field | Value |
| --- | --- |
| **REPOSITORY** | Ceoloo/AION-Revenue-Factory |
| **PATH** | /home/user/AION-Revenue-Factory |
| **REMOTE** | https://github.com/Ceoloo/AION-Revenue-Factory |
| **BRANCH** | claude/aion-p0d-forensics-byek01 |
| **COMMIT** | c4a12aded14b17792e889c043ebc4d839bff30e4 |
| **FRAMEWORK** | Python package, `setuptools` build backend (`pyproject.toml`). Dependency-free core; optional `anthropic>=0.40` extra for the live LLM gateway. |
| **RUNTIME** | CPython >= 3.10. Runs as a CLI (`python -m aion_revenue_factory`) or importable library. **No web server, no serverless runtime, no long-running worker.** |
| **PACKAGE MANAGER** | pip / PEP 517 (`setuptools>=68`). Optional extras: `[live]` (anthropic), `[dev]` (pytest + anthropic). |
| **ENTRYPOINTS** | `src/aion_revenue_factory/__main__.py`; `cli.py:main` (`pyproject.toml` → `[project.scripts] aion-revenue-factory`). |
| **EDGE_FUNCTIONS** | **NONE.** No `supabase/functions/` directory anywhere in the tree. |
| **API_ROUTES** | **NONE.** No `api/`, `app/api/`, `pages/api/`, `server/`, `functions/`, `lambda/`. |
| **WORKERS** | **NONE.** No `workers/`, `jobs/`, queue consumers, or background daemons. |
| **CRON_JOBS** | **NONE.** No `pg_cron`, no `.github/workflows`, no OS cron, no scheduler. The "daily loop" is an in-process Python `for` loop (`RevenueFactory.run_days`), invoked manually. |
| **WEBHOOKS** | **OUTBOUND only.** `WebhookSender` POSTs outreach messages to a user-configured ESP/dialer/voice URL. **No inbound webhook handler exists.** |
| **DATABASE_CODE** | No SQL files, no migrations, no RPC, no triggers, no views. All DB access is **REST-over-HTTP**: Supabase PostgREST `POST` and Airtable REST `POST`. Entity→row mapping lives in `integrations/live/write_through.py`. |
| **EXTERNAL_INTEGRATIONS** | Anthropic/Claude (official SDK), Airtable REST, Supabase PostgREST, a generic HTTP prospect/enrichment API, SMTP, and a generic outbound webhook. |
| **AGENT_SYSTEMS** | In-process "AI employees" = 8 rule-based `departments/`. The "Hermes-style" orchestrator is a **naming reference in a docstring only** — there is no external Hermes/OpenClaw runtime. `KnowledgeBase` is an in-memory analog of "Founder Memory / Learning Loop" and is **not persisted to any database**. |
| **DEPLOYMENT_TARGETS** | pip-installable package. **No** Dockerfile, `vercel.json`, `supabase/config.toml`, `serverless.yml`, Terraform, or CI/CD config of any kind. |
| **ENV CONFIG FILENAMES** | None committed (no `.env`, `.env.example`). Env vars are read directly in `config.py`. `.gitignore` covers `.venv/ venv/ env/` and Python build artifacts. |
| **README / ARCH DOCS** | `README.md`, `docs/ARCHITECTURE.md`. |

### Major application directories

```
src/aion_revenue_factory/
├── domain/            # dataclasses + enums (shared vocabulary; imports nothing)
├── integrations/      # CRM, AIGateway, KnowledgeBase protocols + offline refs
│   └── live/          # LIVE adapters: Airtable, Supabase, Anthropic, HTTP, SMTP, webhook
├── departments/       # 8 rule-based "departments" (business logic)
├── scoring.py         # opportunity scoring
├── orchestrator.py    # RevenueFactory — the in-process daily workflow
├── dashboard.py       # revenue metrics (reads local CRM cache only)
├── config.py          # build_factory_from_env() — env-driven adapter selection
└── cli.py             # CLI entry point
tests/                 # pytest suite (all network mocked)
examples/              # run_week.py, live_wiring.py
docs/ARCHITECTURE.md
```

- **Supabase directories:** NONE.
- **Edge Function directories:** NONE.
- **API directories:** NONE.
- **Workflow / automation / infrastructure directories:** NONE.
- **Agent/runtime directories:** NONE (departments are plain Python modules).

### Environment variable names used (NAMES ONLY — no values, none are secrets)

`ANTHROPIC_API_KEY`, `AION_LLM_MODEL`, `AIRTABLE_API_KEY`, `AIRTABLE_BASE_ID`,
`SUPABASE_URL`, `SUPABASE_KEY`, `AION_PROSPECT_URL`, `AION_PROSPECT_API_KEY`,
`AION_PROSPECT_METHOD`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`,
`SMTP_FROM`, `AION_OUTREACH_WEBHOOK_URL`, `AION_OUTREACH_WEBHOOK_KEY`.

Evidence: `src/aion_revenue_factory/config.py:32-130`.

---

## Inventory table (required P0-D format)

```
REPOSITORY:           Ceoloo/AION-Revenue-Factory
PATH:                 /home/user/AION-Revenue-Factory
BRANCH:               claude/aion-p0d-forensics-byek01
COMMIT:               c4a12aded14b17792e889c043ebc4d839bff30e4
FRAMEWORK:            Python (setuptools) — dependency-free core + optional anthropic SDK
RUNTIME:              CPython >=3.10, CLI / library (no server, no serverless)
ENTRYPOINTS:          __main__.py, cli.py:main, script "aion-revenue-factory"
EDGE_FUNCTIONS:       NONE
API_ROUTES:           NONE
WORKERS:              NONE
CRON_JOBS:            NONE (in-process run_days() loop only)
WEBHOOKS:             OUTBOUND only (WebhookSender -> ESP/dialer/voice URL)
DATABASE_CODE:        REST only — Supabase PostgREST POST, Airtable REST POST; no SQL/RPC/migrations
EXTERNAL_INTEGRATIONS: Anthropic/Claude, Airtable, Supabase, HTTP prospect API, SMTP, webhook
AGENT_SYSTEMS:        In-process rule-based departments; in-memory KnowledgeBase (not persisted)
DEPLOYMENT_TARGETS:   pip package (no container/serverless/IaC config)
```

```
REPOSITORY:           Ceoloo/AION-Advisor-Growth-Engine   -> NOT SCANNED (out of session scope)
REPOSITORY:           Ceoloo/AION-VPS-Empire-Command.V1   -> NOT SCANNED (out of session scope)
REPOSITORY:           Ceoloo/aion-company-os              -> NOT SCANNED (out of session scope)
```
