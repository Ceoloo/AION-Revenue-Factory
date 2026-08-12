# 05 — Workflow / Orchestration Trace

Repository: **Ceoloo/AION-Revenue-Factory**

## Summary

There is exactly **one orchestration mechanism**, and it is **in-process and
manually invoked**. There are **no** GitHub Actions, Supabase scheduled functions,
`pg_cron`, EventBridge, Lambda, n8n, Make, queue consumers, inbound webhooks, or
external agent loops.

| Mechanism | Present? | Evidence |
| --- | --- | --- |
| GitHub Actions | ❌ | no `.github/workflows/` |
| Supabase scheduled functions | ❌ | no `supabase/` |
| `pg_cron` | ❌ | zero matches |
| AWS EventBridge / Lambda / SQS / SNS | ❌ | zero matches |
| n8n / Make | ❌ | zero matches |
| Custom workers / queue consumers | ❌ | none |
| Inbound webhooks | ❌ | only an **outbound** `WebhookSender` |
| OpenClaw / external agent loops | ❌ | zero matches ("Hermes" appears only as a docstring naming style, orchestrator.py:1) |
| Internal scheduler | ⚠️ in-process only | `RevenueFactory.run_days()` loops `run_day()` N times (orchestrator.py:236-237) |

## WORKFLOW: The daily autonomous revenue cycle (in-process)

```
WORKFLOW:          Daily revenue cycle (RevenueFactory.run_day)
TRIGGER:           Manual — cli.py main() / examples / an external caller's own scheduler
                   (the repo ships NO scheduler; "daily" is conceptual)
FIRST COMPONENT:   OpportunityDiscovery.discover()
DATABASE OBJECTS:  opportunities, offers, messages, meetings, proposals, deals,
                   customers, interactions  (WRITE-through only)
EXTERNAL SYSTEMS:  HTTP prospect API (in), Claude (copy), Airtable/Supabase (out),
                   SMTP / ESP webhook (out)
FINAL OUTPUT:      DayResult + Dashboard.metrics(); persisted rows in the live CRM
```

### Step chain (evidence: orchestrator.py:122-234)

```
TRIGGER (manual run_day / run_days)                         cli.py:88-95 / orchestrator.py:236-237
   ↓
STEP 1  discover prospects        discovery.discover(n)     orchestrator.py:129
        └─ live: HttpProspectSource.find() -> prospect API  prospect_sources.py:101-121
   ↓  crm.upsert_opportunity(opp)  -> WRITE opportunities   orchestrator.py:130-131
STEP 2  rank + qualify            discovery.rank/qualified  orchestrator.py:132
   ↓
STEP 3  create offer              offers.create_offer(opp)  orchestrator.py:135
        └─ live: AnthropicGateway.generate() -> Claude      anthropic_gateway.py:56-72
   ↓  crm.save_offer(offer)        -> WRITE offers          orchestrator.py:136
STEP 4  choose channel + compose  outreach.compose(...)     orchestrator.py:138-146
   ↓  outreach.send(msg)  -> live SmtpSender/WebhookSender  orchestrator.py:147; senders.py
   ↓  crm.save_message(msg)        -> WRITE messages        orchestrator.py:148
STEP 5  simulate reply            responses.replies(...)    orchestrator.py:159
        (production: replace ResponseModel w/ real signal)  orchestrator.py:9-11,35-56
   ↓  crm.upsert_deal(deal)        -> WRITE deals           orchestrator.py:161,174,216
STEP 6  book meeting + prep       meeting_prep.prepare()    orchestrator.py:177
   ↓  crm.save_meeting(meeting)    -> WRITE meetings        orchestrator.py:178
STEP 7  proposal + coach          proposals.generate/coach  orchestrator.py:182-186
   ↓  crm.save_proposal(proposal)  -> WRITE proposals       orchestrator.py:187
STEP 8  close + onboard           success.onboard(...)      orchestrator.py:193-199
   ↓  crm.save_customer(customer)  -> WRITE customers       orchestrator.py:200
STEP 9  record + learn            crm.record_interaction()  orchestrator.py:219-221
   ↓  learning.learn_batch(...)  -> updates in-memory KnowledgeBase (NOT persisted)
DATABASE:  all 8 tables (INSERT via write-through, live only)
EXTERNAL:  Airtable / Supabase (out); Claude, prospect API, SMTP/ESP (in/out)
```

### Key properties (with evidence)

- **Determinism:** prospect generation (`SyntheticSource`) and responses
  (`ResponseModel`) are seeded (orchestrator.py:43-56, 82-83). Offline runs are
  reproducible.
- **The learning loop does not persist.** `KnowledgeBase` weights live only in
  process memory (`integrations/knowledge.py:24-27`); `learn_batch` mutates them
  (orchestrator.py:221). Nothing writes these weights to any DB — so cross-run /
  cross-instance learning is **not** durable in this repo. (No `aion_memories` /
  `learning_lessons` persistence.)

See `workflow_trace.json` for the machine-readable form.
