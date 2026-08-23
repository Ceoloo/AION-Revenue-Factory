"""Canonical Supabase Revenue adapter.

Projects Revenue Factory domain objects onto the **canonical live** ``revenue_*``
schema (founder decisions P0-A-REVENUE-001 / P0-E-DOMAIN-001). This is the
source-of-truth projection: ``revenue_leads``, ``revenue_deals``,
``revenue_proposals``, ``revenue_discovery_calls``, ``revenue_activities``,
``revenue_outcomes``, ``revenue_events``. No new tables are introduced.

Every row carries ``source_system='aion_revenue_factory'`` and stashes the full
domain object under ``raw_metadata`` (both columns exist on every revenue_*
table), so the projection is lossless.

Phase 5 correction
------------------
The row builders below were reconciled **field-by-field against the live
production DDL** (see ``docs/PHASE5_SCHEMA_PARITY.md``). The Phase 4 projection
was never inserted (reference sink only), so several rows would have been
*rejected* by the real schema:

* ``revenue_leads`` requires ``universal_record_id`` (NOT NULL, UNIQUE) -- now set.
* ``revenue_deals`` requires ``deal_name`` (NOT NULL) and has **no**
  ``source_record_id`` column -- ``deal_name`` added, ``source_record_id`` removed.
* ``revenue_discovery_calls`` requires ``call_name`` (NOT NULL) -- now set.
* ``revenue_proposals`` requires ``proposal_name`` (NOT NULL) -- now set.
* the ``record_interaction`` -> ``revenue_activities`` row requires
  ``activity_name`` (NOT NULL) -- now set.

``REQUIRED_NOT_NULL`` records the app-supplied NOT-NULL-without-default columns
per table (used by :func:`validate_canonical_row` and the tests) so the
projection can never silently drift from the live schema again.

This adapter is a **reference projection**: it subclasses the in-memory CRM (so
reads -- and therefore dashboard metrics -- are identical to ``InMemoryCRM``),
and records the canonical rows it *would* write via ``_persist``. It performs NO
live database writes; the production write-through path lives in
``production_bridge.py`` and only writes through an authenticated,
RLS-respecting canonical write API (never an embedded service-role key).
Airtable and the in-memory cache remain valid projections and are not removed
(parity must be proven before any cutover).
"""

from __future__ import annotations

from typing import Any

from aion_revenue_factory.integrations.crm import InMemoryCRM

SOURCE_SYSTEM = "aion_revenue_factory"

# The canonical commercial tables (P0-E-DOMAIN-001). The adapter must never
# target anything outside this set -- and in particular never the legacy
# ``opportunities`` / ``deals`` tables.
CANONICAL_TABLES = frozenset(
    {
        "revenue_leads",
        "revenue_contacts",
        "revenue_deals",
        "revenue_proposals",
        "revenue_discovery_calls",
        "revenue_activities",
        "revenue_outcomes",
        "revenue_events",
    }
)

LEGACY_TABLES = frozenset({"opportunities", "deals", "proposals", "customers"})

# App-supplied columns that are NOT NULL and have no database default, per the
# live DDL. A canonical row MUST provide every one of these (non-null).
# Columns with defaults (id, created_at/updated_at, source_system, raw_metadata,
# status) are intentionally omitted -- the database fills them.
REQUIRED_NOT_NULL: dict[str, tuple[str, ...]] = {
    "revenue_leads": ("universal_record_id", "lead_id"),
    "revenue_contacts": ("contact_id",),
    "revenue_deals": ("deal_id", "deal_name"),
    "revenue_proposals": ("proposal_id", "proposal_name"),
    "revenue_discovery_calls": ("discovery_call_id", "call_name"),
    "revenue_activities": ("activity_id", "activity_name"),
    "revenue_outcomes": ("outcome_id",),
    "revenue_events": ("revenue_event_id", "revenue_event"),
}

# The business (natural) key column for each canonical table -- the UNIQUE text
# key the live schema enforces and that foreign keys reference (NOT the uuid
# ``id`` surrogate).
BUSINESS_KEY: dict[str, str] = {
    "revenue_leads": "lead_id",
    "revenue_contacts": "contact_id",
    "revenue_deals": "deal_id",
    "revenue_proposals": "proposal_id",
    "revenue_discovery_calls": "discovery_call_id",
    "revenue_activities": "activity_id",
    "revenue_outcomes": "outcome_id",
    "revenue_events": "revenue_event_id",
}


class CanonicalValidationError(ValueError):
    """A projected row is missing a column the live schema requires NOT NULL."""


def validate_canonical_row(table: str, row: dict) -> None:
    """Raise if ``row`` would be rejected by the live ``table`` DDL.

    Guards the two failure classes the Phase 4 projection was blind to:
    writing a non-canonical table, and omitting a NOT-NULL-without-default
    column.
    """
    if table not in CANONICAL_TABLES:
        raise CanonicalValidationError(
            f"{table!r} is not a canonical revenue_* table "
            f"(canonical only: {sorted(CANONICAL_TABLES)})"
        )
    missing = [
        col
        for col in REQUIRED_NOT_NULL.get(table, ())
        if row.get(col) in (None, "")
    ]
    if missing:
        raise CanonicalValidationError(
            f"{table}: missing required NOT NULL column(s): {missing}"
        )


def _lead_row(o: Any) -> dict:
    return {
        "source_system": SOURCE_SYSTEM,
        # Globally-unique cross-system identity (NOT NULL, UNIQUE on the live
        # table). Namespaced by source so RF-owned rows never collide with
        # Airtable- or opportunity-derived leads.
        "universal_record_id": f"rf::{o.id}",
        "source_record_id": o.id,
        "lead_id": o.id,
        "full_name": o.contact.name if o.contact else "",
        "email": o.contact.email if o.contact else "",
        "role": o.contact.title if o.contact else None,
        "company": o.name,
        "website": o.website,
        "industry": o.industry,
        "country": o.region,
        "lead_score": o.scores.composite,
        "buying_intent": str(o.scores.buying_intent),
        "suggested_price": o.scores.estimated_contract_value,
        "status": "New",
        "raw_metadata": {
            "kind": o.kind,
            "employees": o.employees,
            "source": o.source,
            "signals": o.signals,
            "scores": {
                "revenue_score": o.scores.revenue_score,
                "urgency_score": o.scores.urgency_score,
                "buying_intent": o.scores.buying_intent,
                "contact_confidence": o.scores.contact_confidence,
                "estimated_contract_value": o.scores.estimated_contract_value,
                "composite": o.scores.composite,
            },
        },
    }


def _deal_row(d: Any) -> dict:
    return {
        "source_system": SOURCE_SYSTEM,
        "deal_id": d.id,
        "lead_id": d.opportunity_id,
        # NOT NULL on the live table; deterministic, human-readable.
        "deal_name": f"Deal for {d.opportunity_id}",
        "deal_stage": d.stage.value,
        "deal_value": d.amount,
        "agent_status": d.agent,
        "raw_metadata": {
            "channel": d.channel.value if d.channel else None,
            "progress": d.progress.value,
            "offer_id": d.offer_id,
            "proposal_id": d.proposal_id,
            "workflow": d.workflow,
        },
    }


def _activity_row(m: Any) -> dict:
    return {
        "source_system": SOURCE_SYSTEM,
        "activity_id": m.id,
        "lead_id": m.opportunity_id,
        "activity_name": m.subject,
        "activity_type": "outreach_" + m.channel.value,
        "outcome": m.status,
        "activity_date": m.sent_at.date().isoformat() if m.sent_at else None,
        "raw_metadata": {"channel": m.channel.value, "body": m.body},
    }


def _call_row(mt: Any) -> dict:
    return {
        "source_system": SOURCE_SYSTEM,
        "discovery_call_id": mt.id,
        "lead_id": mt.opportunity_id,
        # NOT NULL on the live table.
        "call_name": f"Discovery call for {mt.opportunity_id}",
        "call_status": "booked",
        "call_date": mt.scheduled_for.isoformat(),
        "raw_metadata": {"scheduled_for": mt.scheduled_for.isoformat()},
    }


def _proposal_row(p: Any) -> dict:
    return {
        "source_system": SOURCE_SYSTEM,
        "proposal_id": p.id,
        "lead_id": p.opportunity_id,
        # NOT NULL on the live table.
        "proposal_name": f"Proposal {p.id}",
        "proposal_value": p.amount,
        "proposal_status": "won" if p.won else "sent",
        "close_probability": None,
        "raw_metadata": {"offer_id": p.offer_id, "payment_link": p.payment_link},
    }


def _outcome_row(c: Any) -> dict:
    return {
        "source_system": SOURCE_SYSTEM,
        "outcome_id": c.id,
        "lead_id": c.opportunity_id,
        "deal_id": c.deal_id,
        "outcome": "won",
        "final_price": c.mrr,
        "churn_risk": str(c.churn_risk),
        "raw_metadata": {"health_score": c.health_score, "mrr": c.mrr},
    }


def _revenue_event_row(c: Any) -> dict:
    return {
        "source_system": SOURCE_SYSTEM,
        "revenue_event_id": c.id,
        "lead_id": c.opportunity_id,
        "deal_id": c.deal_id,
        "revenue_event": "revenue.collected",
        "revenue_status": "collected",
        "amount": c.mrr,
        "mrr_impact": c.mrr,
        "raw_metadata": {"health_score": c.health_score},
    }


def _interaction_row(interaction: Any) -> dict:
    return {
        "source_system": SOURCE_SYSTEM,
        "activity_id": interaction.id,
        "lead_id": interaction.opportunity_id,
        # NOT NULL on the live table -- was missing in Phase 4.
        "activity_name": f"{interaction.step} interaction",
        "activity_type": interaction.step,
        "outcome": interaction.outcome,
        "assigned_rep": interaction.agent,
        "raw_metadata": {
            "channel": interaction.channel.value if interaction.channel else None,
            "value": interaction.value,
            "industry": interaction.industry,
        },
    }


class SupabaseRevenueAdapter(InMemoryCRM):
    """Write-through projection onto the canonical ``revenue_*`` tables.

    Reads are served from the in-memory cache (identical to ``InMemoryCRM``);
    every write is also projected to a canonical row recorded via ``_persist``.
    ``_persist`` is a no-op reference sink here (rows collected in
    ``self.persisted``); the production subclass in ``production_bridge.py``
    routes ``_persist`` through an authenticated canonical write API.
    """

    def __init__(self) -> None:
        super().__init__()
        self.persisted: list[tuple[str, dict]] = []

    # Subclasses override to write through an authenticated canonical API.
    def _persist(self, table: str, row: dict) -> None:
        self.persisted.append((table, row))

    def rows_for(self, table: str) -> list[dict]:
        return [r for t, r in self.persisted if t == table]

    def upsert_opportunity(self, opp) -> None:
        super().upsert_opportunity(opp)
        self._persist("revenue_leads", _lead_row(opp))

    def upsert_deal(self, deal) -> None:
        super().upsert_deal(deal)
        self._persist("revenue_deals", _deal_row(deal))

    def save_message(self, msg) -> None:
        super().save_message(msg)
        self._persist("revenue_activities", _activity_row(msg))

    def save_meeting(self, meeting) -> None:
        super().save_meeting(meeting)
        self._persist("revenue_discovery_calls", _call_row(meeting))

    def save_proposal(self, proposal) -> None:
        super().save_proposal(proposal)
        self._persist("revenue_proposals", _proposal_row(proposal))

    def save_customer(self, customer) -> None:
        super().save_customer(customer)
        self._persist("revenue_outcomes", _outcome_row(customer))
        self._persist("revenue_events", _revenue_event_row(customer))

    def record_interaction(self, interaction) -> None:
        super().record_interaction(interaction)
        self._persist("revenue_activities", _interaction_row(interaction))


def canonical_rows_for(adapter: SupabaseRevenueAdapter, table: str) -> list[dict]:
    """Convenience: the canonical rows an adapter projected for one table."""
    return adapter.rows_for(table)
