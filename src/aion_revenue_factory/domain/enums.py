"""Enumerations shared across the revenue pipeline."""

from __future__ import annotations

from enum import Enum


class Stage(str, Enum):
    """Pipeline stages a deal moves through, in order."""

    NEW = "new"
    CONTACTED = "contacted"
    REPLIED = "replied"
    MEETING_BOOKED = "meeting_booked"
    PROPOSAL_SENT = "proposal_sent"
    WON = "won"
    LOST = "lost"

    @property
    def rank(self) -> int:
        """Ordinal position, used to prevent backwards stage transitions.

        WON sits at the top of the funnel; LOST is an off-funnel terminal state
        (rank -1) so a lost deal never counts as having progressed past where it
        actually dropped — funnel progress is tracked separately on the Deal.
        """
        return _STAGE_ORDER.index(self)

    def is_terminal(self) -> bool:
        return self in (Stage.WON, Stage.LOST)


# LOST first so its rank is -0... we place it so index gives a low rank.
_STAGE_ORDER = [
    Stage.LOST,
    Stage.NEW,
    Stage.CONTACTED,
    Stage.REPLIED,
    Stage.MEETING_BOOKED,
    Stage.PROPOSAL_SENT,
    Stage.WON,
]

# The ordered funnel milestones (excludes terminal WON/LOST) used for progress.
FUNNEL_MILESTONES = [
    Stage.NEW,
    Stage.CONTACTED,
    Stage.REPLIED,
    Stage.MEETING_BOOKED,
    Stage.PROPOSAL_SENT,
]


def funnel_index(stage: "Stage") -> int:
    """Index of a stage within the funnel; WON counts as fully progressed."""
    if stage is Stage.WON:
        return len(FUNNEL_MILESTONES) - 1
    if stage in FUNNEL_MILESTONES:
        return FUNNEL_MILESTONES.index(stage)
    return -1  # LOST


class Channel(str, Enum):
    """Outreach channels handled by the outreach workforce."""

    EMAIL = "email"
    LINKEDIN = "linkedin"
    SMS = "sms"
    COLD_CALL = "cold_call"
    VOICE_AI = "voice_ai"


class OfferType(str, Enum):
    """The kind of personalized offer Offer Intelligence assembles."""

    AUDIT = "audit"
    PROPOSAL = "proposal"
    LANDING_PAGE = "landing_page"
    ROI_CALCULATOR = "roi_calculator"
    CASE_STUDY = "case_study"
    PILOT = "pilot"
