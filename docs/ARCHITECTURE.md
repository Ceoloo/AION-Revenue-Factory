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

| Swap this…                | …for this                                                        |
| ------------------------- | ---------------------------------------------------------------- |
| `InMemoryCRM`             | A `CRM` implementation backed by Airtable / Supabase.            |
| `TemplateGateway`         | An `AIGateway` that calls your AI gateway / LLM for copy.        |
| `SyntheticSource`         | A `ProspectSource` that calls enrichment / search / research APIs.|
| `ResponseModel`           | A live signal that reads real replies, bookings, and closes.     |
| outreach `send` no-op     | A callable that hits your ESP, dialer, or voice-AI provider.     |

Because the orchestrator only depends on the interfaces, wiring production
services is a matter of constructing `RevenueFactory` with the real
implementations injected — the department logic and the daily workflow do not
change.

### Example: injecting a real AI gateway

```python
class MyGateway:  # satisfies integrations.AIGateway
    def generate(self, prompt, context, *, max_words=120):
        return call_my_llm(prompt, context)  # your AI gateway
```

Then construct the departments with `MyGateway()` in place of `TemplateGateway()`
(today done inside `RevenueFactory.__init__`; extract to constructor arguments
when you wire real services).

## Extending

- **New department** — add a module under `departments/`, depend only on
  `domain` + `integrations`, and call it from `RevenueFactory.run_day`.
- **New channel or offer type** — add to the `Channel` / `OfferType` enum; the
  workforce, offer intelligence, learning, and dashboards pick it up.
- **New metric** — add it to `Dashboard.metrics`; it reads only from the CRM.
