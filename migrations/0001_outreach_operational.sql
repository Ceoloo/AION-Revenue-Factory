-- AION Outreach Engine — operational state (migration 0001)
--
-- Durable backing for the send queue, email events, suppression list, campaign
-- membership, messages, and AI generations. Apply to Postgres/Supabase via psql
-- or the Supabase SQL editor. The schema mirrors SqlOutreachStore.ensure_schema
-- exactly, so the application code path is identical on sqlite and Postgres.
--
-- The two integrity guarantees the engine depends on are enforced HERE, by the
-- database, so they survive a restart:
--   * no duplicate sends  -> UNIQUE (idempotency_key) on outreach_queue
--   * idempotent events   -> UNIQUE (dedupe_key) on outreach_events
--
-- Reversible: see the DROP statements at the bottom (commented).

BEGIN;

CREATE TABLE IF NOT EXISTS outreach_campaigns (
    id    TEXT PRIMARY KEY,
    state TEXT,
    name  TEXT,
    data  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS outreach_leads (
    id    TEXT PRIMARY KEY,
    email TEXT,
    data  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS outreach_campaign_leads (
    id          TEXT PRIMARY KEY,
    campaign_id TEXT,
    lead_id     TEXT,
    data        TEXT NOT NULL,
    UNIQUE (campaign_id, lead_id)
);

CREATE TABLE IF NOT EXISTS outreach_queue (
    id              TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,   -- lead_id + campaign_id + step_id
    campaign_id     TEXT,
    lead_id         TEXT,
    step_id         TEXT,
    status          TEXT,
    scheduled_at    TEXT,
    completed_day   TEXT,
    data            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS outreach_messages (
    id                  TEXT PRIMARY KEY,
    provider_message_id TEXT,
    data                TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS outreach_events (
    id          TEXT PRIMARY KEY,
    dedupe_key  TEXT NOT NULL UNIQUE,       -- provider_message_id + event_type
    campaign_id TEXT,
    event_type  TEXT,
    data        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS outreach_generations (
    id          TEXT PRIMARY KEY,
    campaign_id TEXT,
    data        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS outreach_suppression (
    email TEXT PRIMARY KEY,
    data  TEXT NOT NULL
);

-- Indexes for the queries the engine actually runs.
CREATE INDEX IF NOT EXISTS ix_outreach_queue_status      ON outreach_queue (status);
CREATE INDEX IF NOT EXISTS ix_outreach_queue_campaign    ON outreach_queue (campaign_id);
CREATE INDEX IF NOT EXISTS ix_outreach_queue_lead        ON outreach_queue (lead_id);
CREATE INDEX IF NOT EXISTS ix_outreach_queue_sched       ON outreach_queue (scheduled_at);
CREATE INDEX IF NOT EXISTS ix_outreach_queue_sentday     ON outreach_queue (status, completed_day);
CREATE INDEX IF NOT EXISTS ix_outreach_messages_provider ON outreach_messages (provider_message_id);
CREATE INDEX IF NOT EXISTS ix_outreach_events_campaign   ON outreach_events (campaign_id);
CREATE INDEX IF NOT EXISTS ix_outreach_events_type       ON outreach_events (event_type);
CREATE INDEX IF NOT EXISTS ix_outreach_cleads_campaign   ON outreach_campaign_leads (campaign_id);
CREATE INDEX IF NOT EXISTS ix_outreach_generations_camp  ON outreach_generations (campaign_id);

COMMIT;

-- Down migration (reversible):
-- BEGIN;
-- DROP TABLE IF EXISTS outreach_suppression, outreach_generations, outreach_events,
--   outreach_messages, outreach_queue, outreach_campaign_leads, outreach_leads,
--   outreach_campaigns;
-- COMMIT;
