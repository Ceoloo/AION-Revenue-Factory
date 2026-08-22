"""integrations.revenue -- Revenue OS platform-boundary adapters.

Re-exports the existing integration primitives and adds the canonical
:class:`SupabaseRevenueAdapter` (reference projection) plus the Phase 5
production write-through bridge, which projects Revenue Factory domain objects
onto the canonical live ``revenue_*`` schema through an authenticated,
RLS-respecting canonical write API.
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

from .supabase_revenue import (
    CANONICAL_TABLES,
    LEGACY_TABLES,
    REQUIRED_NOT_NULL,
    CanonicalValidationError,
    SupabaseRevenueAdapter,
    canonical_rows_for,
    validate_canonical_row,
)
from .production_bridge import (
    CanonicalWriter,
    ConcurrencyConflict,
    DownstreamWriteError,
    ForeignKeyError,
    InMemoryCanonicalWriter,
    ProductionSupabaseRevenueAdapter,
    RestCanonicalWriter,
    WriteResult,
    build_idempotency_key,
)

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
    # canonical projection
    "SupabaseRevenueAdapter",
    "canonical_rows_for",
    "CANONICAL_TABLES",
    "LEGACY_TABLES",
    "REQUIRED_NOT_NULL",
    "CanonicalValidationError",
    "validate_canonical_row",
    # production write-through bridge
    "ProductionSupabaseRevenueAdapter",
    "CanonicalWriter",
    "InMemoryCanonicalWriter",
    "RestCanonicalWriter",
    "WriteResult",
    "build_idempotency_key",
    "ConcurrencyConflict",
    "ForeignKeyError",
    "DownstreamWriteError",
]
