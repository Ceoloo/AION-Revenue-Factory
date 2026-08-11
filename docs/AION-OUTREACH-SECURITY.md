# AION Outreach Engine — Security & Compliance

## Secret management

- All credentials come from the environment (`RESEND_API_KEY`,
  `RESEND_WEBHOOK_SECRET`, `AIRTABLE_API_KEY`, `ANTHROPIC_API_KEY`). None are
  stored in the operational store or committed to git (`.env` is ignored).
- The structured logger redacts any field whose name contains `api_key`,
  `secret`, `token`, `password`, `authorization`, or `body`, so a careless
  caller can't leak a secret into logs.
- Credentials never cross to a frontend. The HTTP surface exposes only health,
  non-secret dashboard data, and the webhook receiver.

## Webhook verification

- `ResendProvider.parse_webhook` verifies the Svix HMAC-SHA256 signature over
  `{svix-id}.{svix-timestamp}.{body}` using `RESEND_WEBHOOK_SECRET` before any
  state change. Missing secret or bad signature → `PermanentProviderError` →
  HTTP 400, no state mutation.
- Event processing is idempotent on `(provider_message_id, event_type)`, so a
  replayed (or duplicated) webhook cannot cause a double state transition.

## Input validation

- Templates use strict `{{variable}}` substitution: an unresolved variable
  raises `TemplateError` instead of emitting a broken merge field to a prospect.
- Email addresses are shape-validated before send; the provider remains the
  authority on deliverability.
- Webhook bodies are parsed defensively; malformed JSON is rejected.

## Injection / XSS / SQL

- No SQL is issued by V1 (in-memory operational store + Airtable REST via
  parameterized `urllib` requests). When backing the store with SQL, use
  parameterized queries / an ORM — never string interpolation.
- Emails are sent as `text/plain` by the Resend provider in V1, avoiding HTML
  injection in outbound mail. The dashboard/HTTP surface emits JSON only.

## Authentication & authorization

The engine is an internal service. Authn/authz is enforced at the surface that
mounts it:

- The reference HTTP server is intended to run behind the existing AION
  auth/ingress; do not expose it publicly unauthenticated except for the
  signed webhook endpoint.
- Administrative actions (create/activate/pause/stop campaigns, adjust limits,
  cancel queued emails, view suppressed leads) should be gated by the caller's
  existing authorization. Launching a campaign is an explicit, confirmed action.

## Rate limiting & abuse safeguards

- Per-campaign `daily_send_limit` and global `MAX_DAILY_SENDS` are enforced by
  the worker, which refuses to exceed them.
- Sending windows prevent off-hours blasts.
- Retries use bounded exponential backoff; permanent failures are never retried.

## Compliance & sender reputation

The architecture bakes in the compliance requirements:

- **Suppression list** — global, checked before every send; bounces, complaints,
  unsubscribes, and do-not-contact all suppress.
- **Unsubscribe / bounce / complaint handling** — automatic via webhook
  normalization + suppression.
- **Duplicate-send prevention** — idempotency key `lead+campaign+step`.
- **Configured limits enforced**; **domain authentication** (SPF/DKIM/DMARC)
  documented as a launch prerequisite.
- **Accurate sender identity** — `EMAIL_FROM` / `EMAIL_REPLY_TO` on a verified
  domain; no deceptive headers.

The system deliberately contains **no** features to bypass spam filters or evade
provider policies. Test mode redirects sends to `TEST_EMAIL_ADDRESS` while
preserving the true intended recipient in metadata, so testing never
accidentally contacts real prospects.

## Data minimization

- Logs avoid full email bodies (subjects are truncated) and personal data where
  possible.
- AI generations are stored for auditability; treat that store as containing
  prospect data and apply your retention policy.
