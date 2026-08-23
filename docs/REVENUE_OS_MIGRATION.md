# AION Revenue Factory -> Revenue OS Migration (Phase 4)

**Goal:** preserve the Revenue Factory's domain capabilities while removing
duplicate platform infrastructure and making the canonical live ``revenue_*``
schema the operational source of truth. **Additive, non-breaking, CI-validated.
Production traffic is NOT switched** -- parity is proven first.

## Domain vs platform separation

| Capability | Kind | Owner (existing module) | Revenue OS home (facade) |
| --- | --- | --- | --- |
| CRM / prospect / lead / opportunity / deal / customer models | **domain** | `aion_revenue_factory.domain` | (domain stays; consumed everywhere) |
| Discovery, Offer Intelligence, Outreach, Meeting Prep, Proposal, Deal Coach, Customer Success, Learning | **domain** (AI employees) | `aion_revenue_factory.departments` | `agents/revenue` |
| Orchestration (daily workflow), dashboard, CLI, scoring | **domain app** | `orchestrator`, `dashboard`, `cli`, `scoring` | `apps/revenue` |
| CRM store, AI gateway, prospect source, senders, knowledge | **platform boundary** | `aion_revenue_factory.integrations` | `integrations/revenue` |
| Event emission (Event Spine) | **platform** | vendored `aion_events` + `event_sink` | uses AION Core contract |

The domain code is **not physically moved** in this phase: doing so would break
the package's 40+ passing tests for no functional gain. The `apps/revenue`,
`agents/revenue`, `integrations/revenue` packages are the Revenue OS organizing
layer -- thin facades over the tested `aion_revenue_factory` package. A physical
relocation is a later, reconciliation-gated step (rules #3, #10).

## Platform logic uses AION Core

- **Event Spine:** the vendored `aion_events` port emits envelopes conforming to
  the AION Core schema; every state transition below emits one.
- **Execution Gateway / Governance / Audit:** high-risk outreach/billing actions
  are designed to route through the AION Core Agent Execution Gateway
  (`core.execution`, Phase 3) once wired -- via the same adapter pattern.
- **Supabase/Postgres is canonical:** see the data section.

## Canonical operational database

The canonical commercial store is the **live ``revenue_*`` schema** (founder
decisions P0-A-REVENUE-001 / P0-E-DOMAIN-001), NOT the Revenue Factory's default
`opportunities/deals/...` tables (those are the rejected legacy schema).
`integrations/revenue/supabase_revenue.py` (`SupabaseRevenueAdapter`) projects
domain objects onto:

| Domain object | Canonical table |
| --- | --- |
| Opportunity | `revenue_leads` |
| Deal | `revenue_deals` |
| OutreachMessage / Interaction | `revenue_activities` |
| Meeting | `revenue_discovery_calls` |
| Proposal | `revenue_proposals` |
| Customer (won) | `revenue_outcomes` + `revenue_events` |

Every row carries `source_system='aion_revenue_factory'` and the full domain
object under `raw_metadata` (both columns exist on every `revenue_*` table), so
the projection is lossless and reconciles against `revenue_factory_sync_state`.
**No new tables.** The adapter is a reference projection (records rows via
`_persist`; a production subclass writes to Supabase) -- it performs **no live
writes** in this phase.

### Airtable / local cache -> projections (kept, not deleted)

The existing `AirtableCRM`, `SupabaseCRM`, and in-memory cache remain valid and
are **not removed**. `SupabaseRevenueAdapter` subclasses the in-memory CRM, so
reads (and therefore every dashboard metric) are identical -- which is exactly
what the reconciliation tests assert. Airtable stays a downstream projection.

## Preserved revenue workflows + canonical events

| Workflow step | Emitted canonical event(s) |
| --- | --- |
| discovery | `lead.discovered` |
| research / qualification / ranking | `lead.qualified` |
| offer creation | (captured on the deal / proposal) |
| outreach | `outreach.email_sent` / `outreach.linkedin_sent` |
| meeting booking | `appointment.booked` |
| proposal | `proposal.sent` |
| closing (won) | `deal.won`, `revenue.collected` (+ `billing.*`) |
| closing (lost) | `deal.lost` |
| onboarding / customer success | (customer -> `revenue_outcomes`/`revenue_events`) |
| learning | (KnowledgeBase loop; unchanged) |

> Naming: `lead.created` == emitted `lead.discovered`; `outreach.sent` ==
> `outreach.email_sent`/`linkedin_sent`; `meeting.booked` == `appointment.booked`.
> The revenue-domain events `deal.won/deal.lost/proposal.sent/revenue.collected`
> are siblings of the platform finance events `billing.*` (different consumers).

## Reconciliation tests (parity gate)

`tests/test_revenue_os.py`:
- facade identity (no fork/duplication),
- **byte-equal DayResults + dashboard metrics** under `SupabaseRevenueAdapter`
  vs `InMemoryCRM` (parity),
- canonical row projection shape + `source_system`,
- only canonical `revenue_*` tables are written (no new tables),
- revenue lifecycle events emitted + schema-valid,
- emission does not change determinism.

## What did NOT change / rollback

- No domain logic rewritten; no file moved; no table created; no live write.
- Airtable/in-memory/legacy adapters retained.
- Rollback = revert the commit; the Revenue OS layer is additive facades +
  one new adapter, inert unless selected.

## Cutover (NOT in this phase)

Production traffic switches to `SupabaseRevenueAdapter` only after: (1) a
production `_persist` (real Supabase writes) is added and tested against a
branch/staging project, and (2) a live reconciliation run shows `revenue_*`
rows equivalent to the current path. Until then this is dark/parallel.
"""
