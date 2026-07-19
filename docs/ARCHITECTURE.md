# Architecture

This document explains how the reference implementation is put together and how
to replace each simulated piece with a real production service.

## Layers

```
cli / examples
      │
      ▼
orchestrator (RevenueFactory)          ← composes the daily workflow
      │
      ├── departments/                  ← the eight departments (business logic)
      │        │
      │        ▼
      ├── integrations/                 ← CRM, AIGateway, KnowledgeBase (interfaces)
      │
      ▼
domain/                                 ← dataclasses + enums (shared vocabulary)
```

Dependencies point downward only. The `domain` layer imports nothing from the
project; departments depend on `domain` + `integrations`; the orchestrator
depends on everything and wires it together. This is what makes each piece
independently testable and swappable.

## Key design decisions

### Everything external is an interface

`integrations/` defines small `Protocol`s (`CRM`, `AIGateway`, `ProspectSource`)
plus a dependency-free reference implementation of each. Departments accept these
by constructor injection, so no department knows whether it is talking to
Airtable or an in-memory dict.

### Deterministic simulation

Two things are stochastic: which prospects appear (`SyntheticSource`) and how
they respond (`ResponseModel`). Both take an explicit seed, and exploration in
the departments uses seeded RNGs threaded from the orchestrator. As a result an
entire multi-day run is reproducible — essential for tests and for reasoning
about the learning loop.

### Funnel progress is tracked separately from outcome

A `Deal` has both a terminal `stage` (WON/LOST/…) and a `progress` milestone.
A deal lost at outreach is `stage=LOST` but `progress=CONTACTED`, so the
dashboard funnel (contacted ≥ replied ≥ meetings ≥ proposals ≥ won) stays honest
and lost deals never inflate reply/meeting counts.

### Learning is explicit and inspectable

The `KnowledgeBase` holds clamped multiplicative weights over channels, offer
types, and industries. The Learning Engine nudges them from recorded
interactions (closes weigh most; high-volume non-replies weigh least). Selection
is epsilon-greedy so the system exploits winners while continuing to explore.

## Replacing the simulation with production services

Live adapters are provided in `integrations/live/` — you inject them, or let
`config.build_factory_from_env()` select them from environment variables.

| Swap this…                | …for this (shipped in `integrations/live/`)                       |
| ------------------------- | ---------------------------------------------------------------- |
| `InMemoryCRM`             | `AirtableCRM` / `SupabaseCRM` — write-through to the real backend.|
| `TemplateGateway`         | `AnthropicGateway` — real copy from Claude (official SDK).        |
| `SyntheticSource`         | `HttpProspectSource` — any JSON enrichment / search API.         |
| outreach `send` no-op     | `SmtpSender` (email) / `WebhookSender` (ESP, dialer, voice AI).   |
| `ResponseModel`           | Still bespoke — a live signal that reads real replies/closes.    |

`RevenueFactory.__init__` accepts `gateway`, `crm`, `source`, and
`outreach_send` by injection, so wiring production services never touches the
department logic or the daily workflow.

### Injection points

```python
from aion_revenue_factory import RevenueFactory
from aion_revenue_factory.integrations.live import AnthropicGateway, AirtableCRM

factory = RevenueFactory(
    gateway=AnthropicGateway(model="claude-opus-4-8"),
    crm=AirtableCRM(api_key=..., base_id=...),
)
```

Or drive it all from the environment (offline fallback per service):

```python
from aion_revenue_factory import build_factory_from_env
factory = build_factory_from_env()   # see config.py for recognized env vars
```

### Design choices in the live adapters

- **Write-through CRM.** `AirtableCRM` / `SupabaseCRM` extend `InMemoryCRM` and
  mirror every write to the backend via a single `_persist(table, record)` hook
  (`integrations/live/write_through.py`). Reads stay local (fast dashboard), and
  by default a transient backend outage is swallowed rather than crashing the
  revenue loop (`raise_on_error=True` to opt out).
- **Lazy SDK import.** Only `AnthropicGateway` needs a third-party package, and
  it imports `anthropic` inside `__init__` — so importing the core package, or
  even `integrations.live`, never requires it. Everything else is stdlib
  (`urllib`, `smtplib`).
- **Vendor-agnostic prospects.** `HttpProspectSource` takes a `map_record`
  callable so you adapt any vendor's JSON shape without changing the source.
- **Still bespoke: the response signal.** `ResponseModel` simulates replies,
  bookings, and closes. In production, replace it with reads from your CRM /
  inbox / calendar so the learning loop trains on real outcomes.

## Extending

- **New department** — add a module under `departments/`, depend only on
  `domain` + `integrations`, and call it from `RevenueFactory.run_day`.
- **New channel or offer type** — add to the `Channel` / `OfferType` enum; the
  workforce, offer intelligence, learning, and dashboards pick it up.
- **New metric** — add it to `Dashboard.metrics`; it reads only from the CRM.
