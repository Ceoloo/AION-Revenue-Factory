# 08 — Canonical Target Mapping

Repository: **Ceoloo/AION-Revenue-Factory**

Canonical destinations are limited to the three declared AION canonical systems:
**EVENTS**, **REVENUE**, **KNOWLEDGE/MEMORY**. No new canonical systems are invented.
Where evidence is insufficient, the target is `UNRESOLVED`.

| Legacy / observed source | Access in this repo | Canonical target | Confidence | Rationale |
| --- | --- | --- | --- | --- |
| `opportunities` | WRITE | **REVENUE** | HIGH | Core revenue pipeline entity; produced by discovery. write_through.py:157-159 |
| `deals` | WRITE | **REVENUE** | HIGH | Deal lifecycle/stage. write_through.py:161-163 |
| `offers` | WRITE | **REVENUE** | HIGH | Priced offers per prospect. write_through.py:165-167 |
| `proposals` | WRITE | **REVENUE** | HIGH | Proposal + payment link. write_through.py:177-179 |
| `customers` | WRITE | **REVENUE** | HIGH | Won-deal onboarding/MRR. write_through.py:181-183 |
| `meetings` | WRITE | **REVENUE** | HIGH | Booked calls in funnel. write_through.py:173-175 |
| `messages` | WRITE | **REVENUE** | HIGH | Outreach artifacts. write_through.py:169-171 |
| `interactions` | WRITE | **REVENUE** (with EVENTS overlap) | MEDIUM | Each is an outcome-tagged funnel event (`step`, `outcome`, `value`, `agent`) — write_through.py:117-128. Semantically it is the repo's closest thing to an **event** record, but it is written to a revenue CRM table, not an events store. Whether it should feed canonical **EVENTS** vs stay **REVENUE**: see note. |
| `KnowledgeBase` weights (in-memory) | in-proc R/W, not persisted | **KNOWLEDGE/MEMORY** | MEDIUM | Functional match to Founder Memory / Learning Loop, but no persistence exists to bind. knowledge.py:24-71 |
| Canonical **EVENTS** store (`aion_events*`, `operational_events`, …) | none | **UNRESOLVED** | — | Not referenced in this repo at all. Lives elsewhere. |
| Memory legacy tables (`aion_memories`, `learning_lessons`, LEEP) | none | **UNRESOLVED** | — | Not referenced in this repo at all. |
| `aion_system_registry*` / `aion_*_trace` | none | **UNRESOLVED** | — | Not referenced. |

## Note on `interactions` → EVENTS vs REVENUE

`interactions` is the one object with a genuine dual reading. Its row shape
(`_interaction_fields`, write_through.py:117-128) is event-like:
`{step, channel, offer_type, industry, agent, outcome, value}` — one record per
funnel event, appended (`record_interaction`, crm.py:74-75). In a canonical world
these could be the payloads that populate a canonical **EVENTS** stream
(e.g. `revenue_sync_events`-style). But **this repo emits them straight into a CRM
`interactions` table with no event bus** — so the *current* canonical mapping is
REVENUE, and the EVENTS routing is a **design target, not observed behavior**.
Recorded as MEDIUM confidence; the EVENTS binding is UNRESOLVED pending the events
store's owner repo.

## Unmapped-by-design

- **EVENTS** canonical target: **no producer or consumer in this repo.** The gap
  P0-D exists to close is not visible from AION-Revenue-Factory.
- **KNOWLEDGE/MEMORY** canonical target: only an ephemeral in-memory analog exists;
  there is no durable read/write to trace, so the mapping cannot be certified.
