# 02 — Edge Function Inventory

## Result for AION-Revenue-Factory: **ZERO Supabase Edge Functions**

**Confidence: HIGH (direct, exhaustive evidence).**

There is no `supabase/` directory, no `supabase/functions/` directory, no
`Deno.serve` / `serve()` entrypoint, no `index.ts` edge handler, and no
`supabase/config.toml` anywhere in the repository tree.

### Evidence

- Full file listing of the repo (39 files) contains **no** TypeScript/Deno files
  and **no** `supabase/` path. The entire source tree is Python under
  `src/aion_revenue_factory/` plus `tests/`, `examples/`, `docs/`.
- The repository's own architecture doc frames Supabase strictly as a **CRM
  persistence backend reached over PostgREST**, never as a function host:
  `docs/ARCHITECTURE.md:64-70`, `README.md:182`.

### What plays the "compute" role instead (for completeness)

This repo's application logic runs **in-process** inside the Python orchestrator,
not in any edge/serverless function. The nearest analog to "a function that does
work and touches the database" is the write-through CRM persistence path:

| Pseudo-function | File / lines | Trigger (what causes it to run) | What it causes next |
| --- | --- | --- | --- |
| `RevenueFactory.run_day()` | `orchestrator.py:122-234` | Manual call from `cli.py` / `examples`, or a caller's own scheduler | Drives the full funnel; every persisted entity flows to `CRM.*` → (if live) Supabase/Airtable `POST` |
| `WriteThroughCRM.upsert_*/save_*/record_interaction` | `integrations/live/write_through.py:157-187` | Called by `run_day()` on each entity | `_persist(table, record)` → backend `POST` |
| `SupabaseCRM._persist()` | `integrations/live/supabase_crm.py:50-69` | Called by every write-through method when Supabase is the configured CRM | `POST {SUPABASE_URL}/rest/v1/{table}` (INSERT) |
| `AirtableCRM._persist()` | `integrations/live/airtable_crm.py:41-63` | Same, when Airtable is the configured CRM | `POST api.airtable.com/v0/{base}/{table}` |
| `AnthropicGateway.generate()` | `integrations/live/anthropic_gateway.py:56-72` | Called by offer/outreach/proposal departments to produce copy | `messages.create` to Claude API |
| `HttpProspectSource.find()` | `integrations/live/prospect_sources.py:101-121` | Called by `OpportunityDiscovery.discover()` | `GET`/`POST` to prospect API; maps JSON → `Opportunity` |
| `WebhookSender.__call__()` | `integrations/live/senders.py:94-117` | Called by `OutreachWorkforce.send()` | `POST` outreach payload to ESP/dialer/voice URL |
| `SmtpSender.__call__()` | `integrations/live/senders.py:54-75` | Same, for EMAIL channel | SMTP send |

None of these is an Edge Function. There are **no callers external to the repo**,
no HTTP trigger, no `pg_cron` invocation, and no `verify_jwt` config, because there
is no deployed function surface.

### Required P0-D per-function fields

```
FUNCTION NAME:        (none)
TRIGGER TYPE:         N/A — no Edge Functions in this repository
SERVICE ROLE USAGE:   N/A (see note below)
```

**Service-role note:** `SupabaseCRM` sends whatever key is supplied in
`SUPABASE_KEY` as both `apikey` and `Authorization: Bearer` headers
(`supabase_crm.py:57-59`). The module docstring says this may be "a service-role
or anon key" (`supabase_crm.py:8-10`), and a test passes `"servicekey"`
(`tests/test_live_integrations.py:138,143`). So **service-role usage is possible
but not hard-coded** — it depends entirely on which key the operator sets in the
environment. Flagged in `10_DANGEROUS_DEPENDENCIES.md`.

---

## Other repos

Edge Functions for the AION platform (if any) most plausibly live in
`aion-company-os` or `AION-VPS-Empire-Command.V1`. Those repos were **not scanned**
in this session. Status: **UNRESOLVED** (see `12_UNRESOLVED_DEPENDENCIES.md`).
