# AION Outreach Engine — API

The engine's primary API is its Python service surface (the host project is a
library + CLI). An optional stdlib HTTP surface exposes the endpoints that need
a network: the webhook receiver and health/dashboard reads.

## Python API

```python
from aion_revenue_factory.outreach import (
    build_outreach_from_env, OutreachSystem, OutreachConfig,
    Campaign, Lead, CampaignEngine, QueueWorker,
)

system = build_outreach_from_env()      # env-driven, safe offline defaults
engine = system.engine                  # CampaignEngine
worker = system.worker                  # QueueWorker
dash   = system.dashboard               # OutreachDashboard
```

### CampaignEngine

| Method | Purpose |
| --- | --- |
| `create_campaign(campaign)` | Persist a new campaign (DRAFT) |
| `activate / pause / resume / stop / archive(campaign)` | Lifecycle (activate requires ≥1 active step; pause/stop cancel pending) |
| `add_lead(campaign, lead)` / `add_leads(campaign, leads)` | Enroll leads (idempotent) |
| `segment(leads, icp_min=, industries=)` | Filter a lead list into an audience |
| `enqueue_due(campaign, now=)` | Enqueue the next due step for every eligible lead |
| `mark_reply / mark_meeting / mark_opportunity / mark_converted / unsubscribe` | Attribution + stop transitions |
| `stop_lead(campaign_id, lead_id, state, reason)` | Force-stop a lead's sequence |

### QueueWorker

| Method | Purpose |
| --- | --- |
| `process_once(now=, limit=)` | Drain due `PENDING` items; returns `ProcessResult(processed, sent, skipped, failed, reasons)` |

### Eligibility (the one canonical gate)

```python
from aion_revenue_factory.outreach import is_lead_eligible_for_send
result = is_lead_eligible_for_send(lead, campaign, step, store, campaign_lead)
result.eligible   # bool
result.reason     # "ok" | "suppressed" | "unsubscribed" | "duplicate_send" | ...
```

### EmailProvider contract

```python
provider.send_email(OutboundEmail(...)) -> SendResult(provider_message_id, status, timestamp)
provider.get_delivery_status(provider_message_id) -> str
provider.parse_webhook(headers, body) -> list[NormalizedEvent]   # verifies + normalizes
provider.validate_configuration() -> ConfigStatus(ok, detail)
provider.cost_per_email -> float
```

Implementations: `ConsoleProvider` (dry-run), `ResendProvider` (V1),
`AmazonSESProvider` (stub). Selected by `build_provider(config)`.

## HTTP surface (optional reference server)

`python -m aion_revenue_factory.outreach.server --port 8080`

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/health` | Aggregate health (`status`, per-component checks, dry-run/test flags) |
| GET | `/api/health/email` | Email provider config status |
| GET | `/api/health/airtable` | Airtable config status |
| GET | `/api/health/database` | Operational store status |
| GET | `/api/dashboard` | Metrics overview across campaigns (no secrets) |
| POST | `/webhooks/email` | Provider webhook receiver — **signature-verified**; 400 on bad signature/malformed body, never mutating state |

`route(system, method, path, headers, body) -> (status, dict)` is a pure
function you can mount under any host (FastAPI, Lambda, an existing AION route)
instead of running the reference server.

### Webhook event normalization

Provider payloads normalize to internal `EventType` values:

| Resend | Internal |
| --- | --- |
| `email.sent` | `EMAIL_SENT` |
| `email.delivered` | `EMAIL_DELIVERED` |
| `email.bounced` | `EMAIL_BOUNCED` (→ suppress, stop) |
| `email.complained` | `EMAIL_COMPLAINT` (→ suppress, stop) |
| `email.opened` / `email.clicked` | `EMAIL_OPENED` / `EMAIL_CLICKED` |

Processing is idempotent on `(provider_message_id, event_type)` — replays are
ignored.
