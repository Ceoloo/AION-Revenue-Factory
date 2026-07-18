"""The eight departments of the Revenue Factory.

Each department is a focused, testable unit that owns one stage of the revenue
lifecycle. The orchestrator composes them into the daily autonomous workflow.
"""

from .customer_success import CustomerSuccess
from .deal_coach import DealCoach
from .learning_engine import LearningEngine
from .meeting_prep import MeetingPrep
from .offer_intelligence import OfferIntelligence
from .opportunity_discovery import OpportunityDiscovery, ProspectSource, SyntheticSource
from .outreach import OutreachWorkforce
from .proposal import ProposalGenerator

__all__ = [
    "CustomerSuccess",
    "DealCoach",
    "LearningEngine",
    "MeetingPrep",
    "OfferIntelligence",
    "OpportunityDiscovery",
    "ProspectSource",
    "SyntheticSource",
    "OutreachWorkforce",
    "ProposalGenerator",
]
