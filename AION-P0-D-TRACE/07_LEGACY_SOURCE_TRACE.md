# 07 — Legacy Source Trace

Repository: **Ceoloo/AION-Revenue-Factory**

## Headline finding

**None of the canonical AION legacy sources are referenced anywhere in this
repository.** Confirmed by exhaustive full-text search (case-insensitive).

| Legacy source (searched) | Referenced in this repo? |
| --- | --- |
| `events`, `aion_events`, `aion_events_v2` | ❌ no |
| `operational_events`, `memory_events`, `event_memory(.events)` | ❌ no |
| `revenue_sync_events` | ❌ no |
| `aion_memories`, `learning_lessons`, `aion_lessons` | ❌ no |
| `LEEP`, `leep_events`, `leep_extracted_lessons` | ❌ no |
| `founder_memory`, `learning_feedback` | ❌ no |
| `aion_system_registry(_sources)`, `aion_producer_consumer_trace`, `aion_repository_edge_trace` | ❌ no |

**Implication:** the legacy event/memory/registry substrate that P0-D is chartered
to close the gap on **does not live in AION-Revenue-Factory.** It must live in the
unscanned repos and/or directly in the Supabase project. This makes those the
critical follow-up targets.

---

## Revenue-family objects that ARE present

The repo *does* touch the **revenue** legacy family — the CRM entity tables. These
are the only legacy sources with real evidence here. Each is analyzed against the
14 required questions.

### Object group: `opportunities, deals, offers, proposals, customers, meetings, messages, interactions`

(All share the same access pattern in this repo: **write-only, write-through from
the revenue orchestrator.** Answers below apply to the group, with per-object notes
where they differ.)

| # | Question | Answer (evidence) |
| --- | --- | --- |
| 1 | Who writes to it? | Only `WriteThroughCRM` subclasses (`SupabaseCRM` / `AirtableCRM`) driven by `RevenueFactory.run_day` — `write_through.py:157-187`, `orchestrator.py:130-220`. **Within this repo, one writer.** Other repos/systems: UNRESOLVED. |
| 2 | Who reads it? | **No one in this repo reads from the backend.** Dashboard reads the local cache only (`crm.py:77-85`, `dashboard.py`). External readers: UNRESOLVED. |
| 3 | Which functions depend on it? | `run_day` (write), `Dashboard.metrics` (reads cache, not backend). |
| 4 | Which workflows depend on it? | Only the in-process daily cycle (`05_WORKFLOW_TRACE.md`). No `pg_cron`/n8n/etc. |
| 5 | Which external systems depend on it? | Airtable or Supabase receive the writes; SMTP/ESP consume `messages` content indirectly. Downstream BI/consumers: UNRESOLVED. |
| 6 | What canonical system should replace it? | **REVENUE** (these already ARE the revenue-domain tables; canonical mapping in `08_CANONICAL_MAPPING.md`). |
| 7 | Is it currently active? | Active **only when live CRM env vars are set** (`config.py:41-50`); default runtime is in-memory (offline). Live status per deployment: UNRESOLVED. |
| 8 | Is it historical? | No indication in-repo; every write is an INSERT (`Prefer: return=minimal`, no upsert-on-conflict), so append behavior — see risk note. |
| 9 | Is it a source of truth? | Not from this repo's view — this repo treats its **local cache** as read-truth and the backend as a write mirror. Whether Supabase is the org's SoT: UNRESOLVED. |
| 10 | Is it a projection/cache? | The in-repo `InMemoryCRM` is the cache; the Supabase/Airtable copy is a durable **projection of factory output**. |
| 11 | Is it a duplicate? | **Yes, potentially:** Airtable and Supabase hold the *same* schema (`write_through.py` field mappers are backend-agnostic). Only one is active per deployment, but the dual-adapter design invites duplication across environments. |
| 12 | Is it safe to redirect? | UNRESOLVED — depends on unknown external readers (Q2/Q5). No redirect can be certified without reader evidence. |
| 13 | Is it safe to make read-only? | UNRESOLVED — this repo is a *writer*; making these tables read-only would break `run_day` writes. Safe only after confirming the writer is intentionally retired. |
| 14 | Migration transform needed? | Field flattening only. `_*_fields()` already flattens nested `scores`/`contact`/enums into scalar columns (`write_through.py:27-128`). Enum `.value` strings and ISO datetimes are emitted. No complex transform in-repo. |

### Per-object writer evidence

| Object | Writer | Evidence |
| --- | --- | --- |
| `opportunities` | `upsert_opportunity` | write_through.py:157-159 |
| `deals` | `upsert_deal` | write_through.py:161-163 |
| `offers` | `save_offer` | write_through.py:165-167 |
| `messages` | `save_message` | write_through.py:169-171 |
| `meetings` | `save_meeting` | write_through.py:173-175 |
| `proposals` | `save_proposal` | write_through.py:177-179 |
| `customers` | `save_customer` | write_through.py:181-183 |
| `interactions` | `record_interaction` | write_through.py:185-187 |

## Memory/knowledge legacy family

`aion_memories` / `learning_lessons` / LEEP / `founder_memory` are **not persisted**
here. The functional analog — the `KnowledgeBase` weights — lives only in process
memory and is discarded at process exit (`integrations/knowledge.py:24-27`;
`docs/ARCHITECTURE.md:52-57` calls this the "Founder Memory / Learning Loop"
placeholder). So this repo neither reads nor writes any memory legacy table.
Canonical target for the memory family: **KNOWLEDGE/MEMORY**, but the binding is
`UNRESOLVED` (no persistence code exists to trace).
