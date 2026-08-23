"""apps.revenue -- the Revenue OS application surface.

Facade over the tested ``aion_revenue_factory`` package. The physical domain
code stays in that package (so its 40+ passing tests keep passing); this module
is the Revenue OS *organizing layer* -- a full physical relocation is a later,
reconciliation-gated step (see docs/REVENUE_OS_MIGRATION.md), per migration
rules #3 and #10.
"""

from aion_revenue_factory import (
    Dashboard,
    DayResult,
    ResponseModel,
    RevenueFactory,
    build_factory_from_env,
    describe_wiring,
)

__all__ = [
    "RevenueFactory",
    "Dashboard",
    "DayResult",
    "ResponseModel",
    "build_factory_from_env",
    "describe_wiring",
]
