"""integrations.revenue -- Revenue OS platform-boundary adapters.

Re-exports the existing integration primitives and adds the canonical
:class:`SupabaseRevenueAdapter`, which projects Revenue Factory domain objects
onto the canonical live ``revenue_*`` schema.
"""

from aion_revenue_factory.integrations import (
    CRM,
    CollectingSink,
    Event,
    EventSink,
    HttpTelemetrySink,
    InMemoryCRM,
    NullSink,
    new_event,
    validate_event,
)

from .supabase_revenue import SupabaseRevenueAdapter, canonical_rows_for

__all__ = [
    "CRM",
    "InMemoryCRM",
    "EventSink",
    "NullSink",
    "CollectingSink",
    "HttpTelemetrySink",
    "Event",
    "new_event",
    "validate_event",
    "SupabaseRevenueAdapter",
    "canonical_rows_for",
]
