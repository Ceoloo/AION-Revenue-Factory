# 06 — External System Trace

Repository: **Ceoloo/AION-Revenue-Factory**

Every external system this repo reads from or writes to, with direction and evidence.

| EXTERNAL SYSTEM | FILE | FUNCTION | DIRECTION | DATA | SUPABASE OBJECT | CANONICAL SYSTEM |
| --- | --- | --- | --- | --- | --- | --- |
| **Supabase (PostgREST)** | `integrations/live/supabase_crm.py:50-69` | `SupabaseCRM._persist` | **OUT (write)** | 8 entity row types | `opportunities, deals, offers, messages, meetings, proposals, customers, interactions` | REVENUE |
| **Airtable (REST v0)** | `integrations/live/airtable_crm.py:41-63` | `AirtableCRM._persist` | **OUT (write)** | Same 8 entity row types | (mirror of same objects) | REVENUE |
| **Anthropic / Claude** | `integrations/live/anthropic_gateway.py:56-72` | `AnthropicGateway.generate` | **OUT→IN (call+response)** | prompt + prospect context (JSON) → marketing copy | none | KNOWLEDGE (copy generation; not a store) |
| **HTTP prospect / enrichment API** (Apollo / Clearbit / custom) | `integrations/live/prospect_sources.py:101-121` | `HttpProspectSource.find` | **IN (read)** | prospect records → `Opportunity` | none (feeds `opportunities`) | REVENUE (ingest) |
| **SMTP mail server** | `integrations/live/senders.py:54-75` | `SmtpSender.__call__` | **OUT (send)** | EMAIL outreach message | none (mirrors `messages`) | REVENUE (outreach) |
| **Generic outbound webhook** (ESP / dialer / voice-AI) | `integrations/live/senders.py:94-117` | `WebhookSender.__call__` | **OUT (send)** | outreach message JSON | none (mirrors `messages`) | REVENUE (outreach) |

## Direction chains (required format)

```
HTTP prospect API
 ↓  HttpProspectSource.find()            prospect_sources.py:101-121
 ↓  crm.upsert_opportunity()             orchestrator.py:130-131
public.opportunities  (WRITE)
 ↓  Airtable / Supabase                  write_through.py:157-159
AION Revenue System (canonical: REVENUE)
```

```
Claude (Anthropic)
 ↓  AnthropicGateway.generate()          anthropic_gateway.py:56-72
 ↓  offer/outreach/proposal copy         (in-memory)
 ↓  crm.save_offer / save_message / save_proposal
public.offers / messages / proposals  (WRITE)
AION Revenue System (canonical: REVENUE)
```

```
public.messages  (composed outreach)
 ↓  SmtpSender / WebhookSender           senders.py:54-75 / 94-117
SMTP server / ESP / dialer / voice-AI   (external delivery)
```

## Systems explicitly checked and **NOT present**

Confirmed absent by full-text search (zero code references):
**Slack, Discord, Stripe, Notion, HubSpot / other CRMs, AWS (EventBridge / Lambda /
SQS / SNS), n8n, Make, Vercel, OpenClaw, external Hermes runtime, GitHub API calls.**

- "GitHub" appears only in `README.md` prose, not as an integration.
- "Hermes" appears only as an architectural naming style in `orchestrator.py:1`.

## Notes

- The **prospect API is the only inbound external data source.** Its response
  schema is deployment-specific (`map_record` is injectable — `prospect_sources.py:66`),
  so the exact field contract is `UNRESOLVED` per deployment.
- Airtable and Supabase are **mutually exclusive** at runtime: `config.py:41-50`
  selects Airtable first, else Supabase, else in-memory. A single deployment writes
  to at most one of them.

See `external_system_trace.json`.
