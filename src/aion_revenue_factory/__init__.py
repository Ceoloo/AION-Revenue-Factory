"""AION Revenue Factory — an autonomous AI business-development system.

A dependency-free reference implementation of the Revenue Factory vision: eight
departments and specialized AI employees composed by a Hermes-style orchestrator
into a daily autonomous workflow that discovers, qualifies, nurtures, and closes
revenue opportunities, then learns from every outcome to improve over time.

Quick start::

    from aion_revenue_factory import RevenueFactory, Dashboard

    factory = RevenueFactory()
    factory.run_days(5, prospects=50)
    print(Dashboard(factory.crm).metrics())
"""

from .dashboard import Dashboard
from .orchestrator import DayResult, ResponseModel, RevenueFactory

__version__ = "0.1.0"

__all__ = [
    "RevenueFactory",
    "DayResult",
    "ResponseModel",
    "Dashboard",
    "__version__",
]
