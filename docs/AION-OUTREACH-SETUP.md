# AION Outreach Engine — Setup

The engine runs fully offline with zero configuration. Add credentials to take
one integration live at a time. Everything below maps to a variable in
[`.env.example`](../.env.example).

## 0. Install

```bash
pip install -e .            # or: pip install -e '.[live]' for the Claude gateway
pip install pytest && python -m pytest    # verify (96 tests)
```

Run offline immediately:

```bash
python -m aion_revenue_factory.outreach describe-wiring
python -m aion_revenue_factory.outreach dry-run --leads 5 --verbose
```

## 1. Environment variables

Copy `.env.example` to `.env`. The safety-critical defaults are already safe:
`OUTREACH_DRY_RUN=true`, `MAX_DAILY_SENDS=100`, window Mon-Fri 08:30-16:30. See
the example file for the full annotated list. `.env` is git-ignored — never
commit secrets.

## 2. Airtable configuration

Airtable is the source of truth for leads and revenue. Set `AIRTABLE_API_KEY`
(a personal access token with read on the base) and `AIRTABLE_BASE_ID`. The
Leads table should carry the fields in the spec's LEADS schema (First Name,
Company, Email, ICP Score, Unsubscribed, Do Not Contact, Bounce Status, Reply
Status, …). Field names are mapped in
`outreach/leads_source.py::DEFAULT_FIELD_MAP` — override `AIRTABLE_LEADS_TABLE` /
`AIRTABLE_LEADS_VIEW`, or pass a custom `field_map`, to match your base. Do not
rename or delete existing fields; create only missing ones.

## 3. Resend configuration

1. Create a Resend account and API key → `RESEND_API_KEY`.
2. Set `EMAIL_FROM` / `EMAIL_REPLY_TO` on your verified sending domain.
3. Set `EMAIL_PROVIDER=resend` **and** `OUTREACH_DRY_RUN=false` to send for real.

## 4. Domain authentication

Before any real send, authenticate the sending domain in Resend: add the
SPF, DKIM, and DMARC records Resend provides for `EMAIL_FROM`'s domain and wait
for verification. Unauthenticated domains harm deliverability and sender
reputation.

## 5. Webhook configuration

1. In Resend, add a webhook pointing at your receiver
   (`POST /webhooks/email` on the reference server, or your own route calling
   `WebhookProcessor.handle`).
2. Copy the signing secret → `RESEND_WEBHOOK_SECRET`.
3. Subscribe to `email.sent`, `email.delivered`, `email.bounced`,
   `email.complained`. Signatures are verified (Svix HMAC-SHA256); without the
   secret the receiver rejects every payload.

Run the reference receiver:

```bash
python -m aion_revenue_factory.outreach.server --port 8080
```

## 6. Database migrations

V1 ships an in-memory operational store (`InMemoryOutreachStore`) plus the
existing Airtable/Supabase write-through CRM for persisted entities. There is no
new database server to migrate. When you back the operational store with
Postgres/Supabase, add migrations under a `migrations/` directory (create the
`send_queue`, `email_events`, `suppression_list`, `campaign_leads`,
`ai_generations` tables with the indexes and unique constraints named in
`docs/AION-OUTREACH-ARCHITECTURE.md`) and apply them via your existing migration
tool — never mutate a production database by hand.

## 7. Dry-run mode

`OUTREACH_DRY_RUN=true` (the default) routes every send to the console provider:
personalization, queue records, and intended recipients/subjects/bodies are all
produced and logged, but **no email is sent**. Mandatory before production.

```bash
python -m aion_revenue_factory.outreach dry-run --leads 5 --verbose
```

## 8. Test mode

Set `TEST_EMAIL_ADDRESS=qa@yourdomain.com`. All real sends redirect there while
the intended recipient is preserved in message metadata and tags — safe
end-to-end testing against the real provider.

## 9. Launching a campaign

Launching is explicit and human-confirmed:

1. Seed / create the campaign (starts as `DRAFT`).
2. Enroll a segmented lead list.
3. Dry-run and review intended sends.
4. Authenticate the domain, configure webhooks.
5. Set `OUTREACH_DRY_RUN=false`, `EMAIL_PROVIDER=resend`.
6. Activate the campaign (`CampaignEngine.activate`) — refused if it has no
   active steps.
7. Run `enqueue_due` then `queue:process` on a schedule.

## 10. Pausing a campaign

`CampaignEngine.pause(campaign)` sets state `PAUSED` and cancels all pending
queue items. `resume(campaign)` returns it to `ACTIVE`.

## 11. Handling bounces

Bounce webhooks (`email.bounced`) are normalized to `EMAIL_BOUNCED`,
add the address to the suppression list (reason `BOUNCED`), mark the lead
`bounced=True`, and stop the lead's sequence — automatically.

## 12. Handling unsubscribes

Complaints (`email.complained`) suppress with reason `COMPLAINT`. A first-party
unsubscribe should call `CampaignEngine.unsubscribe(campaign_id, lead_id)`,
which suppresses (`UNSUBSCRIBED`) and stops the sequence. Suppressed addresses
are never contacted again — the eligibility gate blocks them before every send.

## 13. Migrating from Resend to SES

The campaign engine only knows the `EmailProvider` interface, so migration is
configuration plus implementing the SES stub:

1. Implement `AmazonSESProvider.send_email` (SES `SendEmailV2`, return the SES
   `MessageId` as `provider_message_id`).
2. Implement `parse_webhook` to verify SNS signatures and map
   `Bounce`/`Complaint`/`Delivery` to the existing internal events.
3. Set `EMAIL_PROVIDER=ses` + AWS credentials. No campaign, queue, eligibility,
   or webhook-normalization code changes.
