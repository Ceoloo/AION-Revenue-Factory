"""agents.revenue -- the Revenue OS AI employees (departments).

Facade over ``aion_revenue_factory.departments``. These are the domain agents
(Opportunity Discovery, Offer Intelligence, Outreach Workforce, Meeting Prep,
Proposal Generator, Deal Coach, Customer Success, Learning Engine). Domain
logic is unchanged; this is the Revenue OS organizing layer.
"""

from aion_revenue_factory.departments import (
    CustomerSuccess,
    DealCoach,
    LearningEngine,
    MeetingPrep,
    OfferIntelligence,
    OpportunityDiscovery,
    OutreachWorkforce,
    ProposalGenerator,
    SyntheticSource,
)

__all__ = [
    "OpportunityDiscovery",
    "OfferIntelligence",
    "OutreachWorkforce",
    "MeetingPrep",
    "ProposalGenerator",
    "DealCoach",
    "CustomerSuccess",
    "LearningEngine",
    "SyntheticSource",
]
