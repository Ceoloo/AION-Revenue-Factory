# AION Revenue Factory

**An autonomous AI business-development system that finds, qualifies, nurtures, and closes revenue opportunities 24/7.**

Unlike a CRM, this is an autonomous *revenue workforce*. It sits on top of your
existing infrastructure and continuously generates opportunities, executes
outreach, learns from results, and improves over time.

This repository is a **dependency-free, runnable reference implementation** of
that vision. Every department, AI employee, the daily autonomous workflow, the
revenue dashboard, and the self-improving learning loop are modeled as real,
tested Python you can run today — with clean interfaces where your production
services (Airtable, Supabase, an AI gateway, Founder Memory, the Learning Loop)
plug in.

---

## Quick start

No dependencies are required to run it (pytest is only needed for the tests).

```bash
# Run the autonomous loop for 5 business days and print the dashboard
python -m aion_revenue_factory --days 5 --prospects 50

# Machine-readable output
python -m aion_revenue_factory --days 5 --json
```

Or from Python:

```python
from aion_revenue_factory import RevenueFactory, Dashboard

factory = RevenueFactory()
factory.run_days(5, prospects=50)
print(Dashboard(factory.crm).metrics())
```

Run the tests:

```bash
pip install pytest
python -m pytest
```

---

## How it plugs into your stack

```
Founder Memory ─▶ Knowledge Graph ─▶ Revenue Factory
                                          │
                     ┌────────────────────┼────────────────────┐
                    Sales             Marketing            Partnerships
                     └────────────────────┼────────────────────┘
                                          ▼
                                    Airtable CRM
                                          ▼
                                    Learning Loop
                                          ▼
                                    Better offers
```

The factory **leverages** your existing services rather than replacing them.
Each is an interface with a dependency-free reference implementation you swap
out for the real thing:

| Vision component        | Interface (`integrations/`)      | Reference implementation |
| ----------------------- | -------------------------------- | ------------------------ |
| Airtable / Supabase CRM | `CRM`                            | `InMemoryCRM`            |
| AI gateway (LLM)        | `AIGateway`                      | `TemplateGateway`        |
| Founder Memory / Learning Loop | `KnowledgeBase`           | (built in)               |
| Prospect APIs / research | `ProspectSource`                | `SyntheticSource`        |
| ESP / dialer / voice    | `send` callable on the workforce | offline no-op            |

Because everything is behind an interface, the same orchestrator that runs the
offline simulation drives production once the real services are injected.

---

## The eight departments

Each lives in `src/aion_revenue_factory/departments/` as a focused, tested unit.

1. **Opportunity Discovery** — finds businesses, creators, agencies, investors,
   and acquisition targets, then attaches a revenue score, urgency score, buying
   intent, contact confidence, and estimated contract value to each.
2. **Offer Intelligence** — assembles a *personalized* offer per prospect
   (audit, ROI calculator, pilot…), priced from estimated contract value, using
   the format the learning loop says converts best.
3. **Outreach Workforce** — channel-specialized AI employees (email, LinkedIn,
   SMS, cold call, voice AI) that compose and send outreach.
4. **Meeting Preparation** — builds a briefing pack (company profile, decision
   makers, pain points, competitors, objections, pricing recommendation).
5. **Proposal Generator** — produces the proposal, implementation plan, and
   payment link within minutes of a meeting.
6. **Deal Coach** — recommends discounts, upsells, objection handling, timing,
   and strategy, and estimates close probability from historical data.
7. **Customer Success** — onboards won deals, tracks account health, flags churn
   risk, and surfaces upsells.
8. **Learning Engine** — turns every interaction into reinforcement signal so
   tomorrow's choices beat today's.

## AI employees

The departments are staffed by specialized roles that show up in the revenue
attribution: **Research Analyst**, **Copywriter**, **SDR** (per channel),
**Voice AI Agent**, **Proposal Writer**, **Negotiator**, **Customer Success**,
and **Revenue Analyst**.

---

## The daily autonomous workflow

The Hermes-style orchestrator (`orchestrator.py`) composes the departments into
one loop:

```
find 50 businesses ─▶ research ─▶ rank ─▶ create offers ─▶ write outreach
   ─▶ send ─▶ follow up ─▶ book meetings ─▶ prep ─▶ generate proposals
   ─▶ coach ─▶ close ─▶ onboard ─▶ update CRM ─▶ measure ─▶ improve ─▶ repeat
```

Prospect responses are produced by a seeded `ResponseModel` so the whole run is
**deterministic and offline**. Swap it for a live model that reads real replies
and the same orchestration drives production.

## The self-improving loop

Every closed (and lost) deal feeds the `KnowledgeBase`, which holds
multiplicative weights over channels, offer types, and industries. The Learning
Engine reinforces what converts; Offer Intelligence and the Outreach Workforce
read those weights (epsilon-greedy — mostly exploit, always keep exploring) so
the system compounds:

```
prospect ─▶ outreach ─▶ meeting ─▶ proposal ─▶ sale ─▶ success
   ─▶ retention ─▶ referral ─▶ learning ─▶ model improvement ─▶ (repeat, better)
```

## The revenue dashboard

`Dashboard(crm).metrics()` computes the live metrics from the vision: today's
revenue, pipeline value, MRR/ARR, close rate, average deal size, CAC, LTV, lead
velocity, reply rate, booked calls, proposal win %, and revenue broken down by
AI agent, workflow, offer, and industry.

---

## Project layout

```
src/aion_revenue_factory/
├── domain/            # dataclasses + enums: the shared vocabulary
├── integrations/      # CRM, AI gateway, knowledge base (interfaces + refs)
├── departments/       # the eight departments
├── scoring.py         # opportunity scoring
├── orchestrator.py    # the Hermes-style daily workflow
├── dashboard.py       # live revenue metrics
└── cli.py             # `python -m aion_revenue_factory`
tests/                 # pytest suite
examples/              # runnable examples
docs/ARCHITECTURE.md   # deeper design notes + production wiring
```

## Wiring in production services

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for how to replace each
reference implementation with Airtable/Supabase, your AI gateway, real prospect
APIs, and a live response signal — without touching the departments or the
orchestrator.

## Status

This is a foundation, not a finished product: the intelligence is intentionally
rule-based and the data is simulated so the whole system runs offline,
deterministically, and under test. It is designed to be extended service by
service.
