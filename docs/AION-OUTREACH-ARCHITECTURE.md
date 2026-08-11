# AION Outreach Engine — Architecture

> V1 email-campaign orchestration for AION. This document is written **before**
> major implementation and records the infrastructure audit, the design
> decisions, and the migration path to Amazon SES.

## 1. Existing infrastructure (audit result)

The AION Revenue Factory is a **dependency-free Python 3.10+ package**
(`aion_revenue_factory`), not a Next.js/TypeScript/Supabase web app. The
Outreach Engine is built to match what already exists rather than introduce a
second stack.

| Concern | What exists today | Outreach Engine decision |
| --- | --- | --- |
| Language / runtime | Python 3.10+, standard library only (`anthropic` is the only optional live dep) | Same — stdlib only |
| Packaging | `pyproject.toml`, setuptools, `python -m aion_revenue_factory` | Extend the same package; add `outreach` subpackage + CLI verbs |
| Storage abstraction | `CRM` Protocol + `InMemoryCRM` + `WriteThroughCRM` → `AirtableCRM`, `SupabaseCRM` | **Reuse.** Add a parallel `OutreachStore` for high-volume operational state (queue, events) |
| AI | `AIGateway` Protocol + `TemplateGateway` + live `AnthropicGateway` | **Reuse** for personalization |
| Env wiring | `build_factory_from_env()` / `describe_wiring()` | Mirror with `build_outreach_from_env()` / `describe_outreach_wiring()` |
| Email transport | generic `send(msg)->status` callable + `SmtpSender`, `WebhookSender` | Superseded by a first-class `EmailProvider` abstraction (Resend V1, SES stub) |
| Tests | pytest, deterministic/offline | Same — every engine rule is unit-tested offline |
| Dashboard | `Dashboard(crm).metrics()` text/JSON | Mirror with `OutreachDashboard` + CLI + optional stdlib HTTP surface |

**Canonical-implementation decisions**

- **Storage:** Airtable remains the CRM / source-of-truth for lead & revenue
  relationships. High-volume operational state (send queue, email events,
  suppression) lives in the `OutreachStore`. Three implementations satisfy the
  identical protocol: `InMemoryOutreachStore` (dev), `SqliteOutreachStore`
  (durable, stdlib), and `PostgresOutreachStore` (durable, Postgres/Supabase via
  `psycopg`). Selection is `DATABASE_URL`-driven — the engine never changes. The
  SQL stores enforce the no-duplicate-send and idempotent-event guarantees with
  database `UNIQUE` constraints, so they survive process restarts.
- **Email:** the existing generic `send()` callable is too thin for delivery
  status, webhooks, and config validation. V1 introduces the richer
  `EmailProvider` abstraction. `SmtpSender`/`WebhookSender` remain for the
  legacy single-shot `OutreachWorkforce`; the campaign engine only speaks
  `EmailProvider`.
- **AI:** reuse `AIGateway`. No new AI stack.

## 2. Where the Outreach Engine fits

```
Airtable CRM ──▶ Lead sync ──▶ Campaign Engine ──▶ AI Personalization
                                      │                     │
                                      ▼                     ▼
                              Eligibility + Suppression   Template engine
                                      │
                                      ▼
                                 Send Queue ──▶ Worker ──▶ EmailProvider (Resend V1 / SES later)
                                                              │
                                                              ▼
                                                        Webhook events
                                                              │
                                                              ▼
                                                       Event Processor (idempotent)
                                                              │
                                                              ▼
                                          Campaign / Lead state  ──▶  Airtable + OutreachStore
                                                              │
                                                              ▼
                                                     Dashboard / Analytics
```

## 3. Modules (`aion_revenue_factory/outreach/`)

| Module | Responsibility |
| --- | --- |
| `enums.py`, `models.py` | Campaign, CampaignStep, Lead, CampaignLead, EmailMessage, EmailEvent, QueueItem, SuppressionEntry, AIGeneration + states |
| `config.py` | `OutreachConfig` — env-driven: dry-run, test mode, limits, sending window, timezone, provider selection, from/reply-to, retry policy |
| `store.py` | `OutreachStore` Protocol + `InMemoryOutreachStore` (operational state, unique-key duplicate guard) |
| `stores.py` | Durable stores: `SqlOutreachStore` + `SqliteOutreachStore` (stdlib) + `PostgresOutreachStore` (psycopg) — same protocol, DB-enforced idempotency |
| `serialization.py` | Lossless model ⇄ JSON (used by the SQL stores) |
| `templates.py` | Strict `{{variable}}` rendering — unknown/missing variables fail validation |
| `suppression.py` | Global suppression list (`check`, `add`) keyed by email |
| `eligibility.py` | **The one canonical** `is_lead_eligible_for_send()` — every stop condition, nowhere else |
| `personalization.py` | `AIPersonalizer` over `AIGateway` → structured `{subject, body, rationale, confidence}` + validation, cost, audit record |
| `scheduling.py` | Sending window + step schedule math; UTC storage, timezone-aware conversion |
| `providers/` | `EmailProvider` protocol + `ResendProvider`, `ConsoleProvider` (dry-run), `AmazonSESProvider` stub |
| `queue.py` | `SendQueue` + `QueueWorker` — retry/backoff, permanent-failure handling, rate + window enforcement, idempotency |
| `engine.py` | `CampaignEngine` — create/segment/schedule, enqueue eligible, sequence progression, pause/resume/stop |
| `webhooks.py` | `WebhookProcessor` — signature verify, normalize provider→internal events, **idempotent** state transitions |
| `reply_detection.py` | `InboundEmailProvider` protocol + `ReplyDetectionService` — interface only, marked **PENDING** (no faked replies) |
| `metrics.py` | `OutreachDashboard` — reply/positive/meeting/opportunity/close rates, revenue-per-lead/email, ROI |
| `costs.py` | Cost abstraction: `cost_per_email`, `estimated_cost_per_generation` → CAC/ROI |
| `logging.py` | Structured logger (`request_id`, `campaign_id`, `lead_id`, `queue_id`, `provider`, `event_type`) |
| `health.py` | Health checks (database/store, email, airtable) |
| `seed.py` | Seed **AION Electrical Contractor Pilot** as `DRAFT` (never auto-sends) + sample template |
| `server.py` | Optional stdlib `http.server` reference app: `/api/health*`, webhook endpoint, dashboard JSON |
| `wiring.py` | `build_outreach_from_env()` / `describe_outreach_wiring()` |

## 4. Data flow (single step send)

1. `CampaignEngine.enqueue_due(campaign)` walks each active `CampaignLead`,
   computes the next step's scheduled time from the sequence delay + sending
   window, and calls `is_lead_eligible_for_send(lead, campaign, step, store)`.
2. Eligible → a `QueueItem` is created with the **idempotency key**
   `lead_id + campaign_id + step_id`. A unique constraint (enforced in the
   store) makes a duplicate enqueue a no-op.
3. `QueueWorker.process_once()` pulls due `PENDING` items whose
   `scheduled_at <= now` and that pass the window + daily-limit check,
   re-checks eligibility + suppression, personalizes + renders, then calls
   `EmailProvider.send_email()`.
4. The provider returns `SendResult(provider_message_id, status, timestamp)`.
   The queue item moves to `SENT`; an `EmailMessage` is stored; the
   `CampaignLead` advances to `SENT`.
5. Delivery/bounce/complaint arrive via the provider webhook →
   `WebhookProcessor` verifies signature, normalizes to
   `EMAIL_DELIVERED/BOUNCED/COMPLAINT/FAILED`, dedupes on
   `(provider_message_id, event_type)`, updates lead state, and (bounce/
   complaint) writes the suppression list.

## 5. API architecture

Because the host project is a library + CLI, the engine's public surface is
its Python services and the `outreach` CLI verbs. An **optional** stdlib
`http.server` reference app (`outreach/server.py`) exposes the webhook receiver
and health/dashboard endpoints so the system is runnable end-to-end without
adding a web framework. Any real HTTP host (FastAPI, a Lambda, an existing AION
route) mounts `WebhookProcessor.handle()` and `health.*` the same way.

## 6. Queue architecture

In-process, store-backed queue with an idempotent worker. Statuses:
`PENDING → PROCESSING → SENT | FAILED | CANCELLED`. Retries use exponential
backoff (`base * 2^attempt`) up to `max_attempts`; **permanent** failures
(invalid recipient, suppressed, hard bounce) are not retried. The worker
enforces the sending window, the per-campaign `daily_send_limit`, and the
global `MAX_DAILY_SENDS` — it **refuses** to exceed configured limits.

## 7. Deployment architecture

Ships inside the existing package. Operate via the `outreach` CLI verbs
(`campaigns:list`, `queue:process`, `dry-run`, …) on a schedule (cron / the
existing AION scheduler). No new services are required for V1; the optional
HTTP surface can run under any process manager when webhooks are needed.

## 8. Security model

- Secrets only via environment (`RESEND_API_KEY`, `RESEND_WEBHOOK_SECRET`,
  `AIRTABLE_API_KEY`, …). Never stored in the DB, never logged.
- Webhook signatures verified (Svix/HMAC-SHA256) before any state change.
- Strict template validation prevents broken/injected merge fields.
- Structured logs omit secrets and full email bodies by default.
- Provider credentials never cross to any frontend; the HTTP surface exposes
  only health + non-secret dashboard data + the webhook receiver.

## 9. Future migration path to SES

`EmailProvider` is the only seam the campaign engine knows. `AmazonSESProvider`
is a documented stub implementing the same protocol. Migration is
config-only: set `EMAIL_PROVIDER=ses` (+ AWS creds). No campaign, queue,
eligibility, or webhook-normalization logic changes — the webhook layer already
normalizes provider-specific payloads into internal event types, so SES's SNS
notifications map onto the same `EMAIL_DELIVERED/BOUNCED/COMPLAINT` events.
