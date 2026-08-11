# AION Outreach Engine — Operations

Day-to-day running of the engine.

## CLI

```bash
python -m aion_revenue_factory.outreach describe-wiring   # live vs offline
python -m aion_revenue_factory.outreach health            # integration health
python -m aion_revenue_factory.outreach seed              # print pilot (DRAFT)
python -m aion_revenue_factory.outreach dry-run --leads 5 [--verbose]
python -m aion_revenue_factory.outreach test-email --to you@example.com
```

The `aion-outreach` console script is installed by `pip install -e .` and is
equivalent to `python -m aion_revenue_factory.outreach`.

## The operational loop

In a scheduled job (cron / the existing AION scheduler), for each `ACTIVE`
campaign:

```python
from aion_revenue_factory.outreach import build_outreach_from_env, build_pilot_campaign

system = build_outreach_from_env()
# ... load/create campaign, enroll segmented leads ...
system.engine.enqueue_due(campaign)     # schedule next due step per eligible lead
system.worker.process_once(limit=100)   # drain due queue items, respecting limits
system.reply_poll = None                # reply detection: PENDING (see below)
```

- `enqueue_due` only enqueues leads that pass the canonical eligibility gate and
  never double-enqueues a `lead+campaign+step` (idempotency key).
- `process_once` enforces the sending window and daily limits, re-checks
  eligibility + suppression at send time, personalizes, sends, and records the
  message/event/state transition. It returns a `ProcessResult` summary.

## Durable operational store

Set `DATABASE_URL` so operational state survives restarts:

```bash
export DATABASE_URL=sqlite:///outreach.db              # durable, stdlib only
export DATABASE_URL=postgresql://user:pass@host/db     # Postgres/Supabase
```

`describe-wiring` and `/api/health` report which store is active. In-memory
(unset `DATABASE_URL`) is dev-only — a restart drops the queue. With a durable
store, queued sends persist across restarts and the database's unique
constraints prevent duplicate sends / duplicate event processing even after a
crash mid-batch. Switching stores changes no engine code (identical
`OutreachStore` interface).

## Running multiple workers

The worker is safe to run concurrently across processes/hosts against one
durable store. Each `process_once` cycle:

1. **Reclaims stale claims** — items a crashed worker left in `PROCESSING`
   longer than `OUTREACH_CLAIM_STALE_SECONDS` (default 900s) return to
   `PENDING`, so no send is lost when a worker dies mid-batch.
2. **Claims atomically** — due items are claimed with Postgres
   `SELECT ... FOR UPDATE SKIP LOCKED` (sqlite uses `BEGIN IMMEDIATE` + a
   conditional `UPDATE ... WHERE status='pending'` guard). Two workers never
   claim the same item, so the same email is never sent twice.
3. **Processes only what it claimed**, releasing items back to `PENDING` when a
   per-campaign daily limit defers them.

Give each worker a distinct identity via `worker_id` (defaults to
`host:pid:rand`); it appears in the structured `queue.reclaimed` / `email.sent`
logs so sends are attributable. No coordinator or lock server is required — the
database is the coordination point. Set `OUTREACH_CLAIM_STALE_SECONDS` above
your longest realistic single-send time so healthy-but-slow sends aren't
reclaimed out from under a worker.

## Queue management

Statuses: `PENDING → PROCESSING → SENT | FAILED | CANCELLED`.

```python
from aion_revenue_factory.outreach import QueueStatus
pending  = system.store.queue_items(QueueStatus.PENDING)
failed   = system.store.queue_items(QueueStatus.FAILED)
```

- Transient send failures retry with exponential backoff up to
  `OUTREACH_MAX_ATTEMPTS`; exhausted items become `FAILED`.
- Permanent failures (rejected recipient/content) go straight to `FAILED` — no
  retries.
- Pausing/stopping a campaign cancels its pending items.

## Sending policy

- Default window: Mon-Fri 08:30-16:30 in `DEFAULT_TIMEZONE`. Items due outside
  the window are held (not failed) until the window opens.
- Daily caps: per-campaign `daily_send_limit` and global `MAX_DAILY_SENDS`. The
  worker refuses to exceed either.

## Reply detection (PENDING)

V1 ships the `InboundEmailProvider` interface and `ReplyDetectionService` but no
concrete inbound provider — the system never invents a reply. `system` reports
this in `describe-wiring` and health. To wire it, implement
`InboundEmailProvider.fetch_replies()` (IMAP/Gmail/provider inbound-parse) and
inject it; detected replies then stop the sequence automatically. Until then,
record replies explicitly via `engine.mark_reply(campaign_id, lead_id,
positive=…)`.

## Revenue attribution transitions

As deals progress, feed signals back so metrics/ROI stay accurate:

```python
system.engine.mark_reply(cid, lid, positive=True)
system.engine.mark_meeting(cid, lid)
system.engine.mark_opportunity(cid, lid)
system.engine.mark_converted(cid, lid, revenue=5000.0)
system.engine.unsubscribe(cid, lid)
```

All of these are also hard stop conditions where appropriate (reply, meeting,
conversion, unsubscribe all end the sequence).

## Metrics

```python
system.dashboard.campaign_metrics(campaign)   # per-campaign funnel + ROI
system.dashboard.overview()                   # across all campaigns
```

ROI = `(revenue - total_cost) / total_cost`; with no cost data it returns
`"Not enough cost data"` rather than a misleading infinite ROI.

## Health & observability

```bash
curl localhost:8080/api/health
curl localhost:8080/api/health/email
curl localhost:8080/api/dashboard
```

Structured logs (one JSON object per event) carry `request_id`, `campaign_id`,
`lead_id`, `queue_id`, `provider`, `event_type`. Secrets and full email bodies
are never logged.

## Incident playbook

- **Deliverability drop / spam complaints**: pause affected campaigns, confirm
  domain auth (SPF/DKIM/DMARC), review suppression growth, lower daily limits.
- **Provider outage**: transient sends retry automatically; if prolonged, pause
  campaigns to stop the retry churn, resume when healthy.
- **Airtable outage**: lead sync fails loudly; operational state (queue/events)
  is unaffected since it lives in the operational store.
