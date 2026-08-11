"""The single canonical eligibility gate.

Every stop condition in the spec lives *here and nowhere else*. The queue, the
worker, and the campaign engine all call :func:`is_lead_eligible_for_send`;
none of them re-implement any part of the rule. That is the whole point — one
place to reason about "should this email go out?".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .enums import CampaignState
from .models import Campaign, CampaignLead, CampaignStep, Lead
from .store import OutreachStore

# Deliberately permissive but non-empty email shape check. The provider is the
# real authority on deliverability; this just rejects obvious garbage early.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class Eligibility:
    """Result of an eligibility check: eligible plus a machine-readable reason."""

    eligible: bool
    reason: str = "ok"

    def __bool__(self) -> bool:  # allows `if eligibility:`
        return self.eligible


def valid_email(email: str) -> bool:
    return bool(email) and bool(_EMAIL_RE.match(email.strip()))


def is_lead_eligible_for_send(
    lead: Lead,
    campaign: Campaign,
    step: Optional[CampaignStep],
    store: OutreachStore,
    campaign_lead: Optional[CampaignLead] = None,
) -> Eligibility:
    """Return whether ``lead`` may receive ``step`` of ``campaign`` right now.

    Checks, in order (cheapest / most decisive first):

    1. valid email
    2. not globally suppressed
    3. not unsubscribed / bounced / do-not-contact
    4. no reply, no meeting, not converted (lead is a customer)
    5. campaign is ACTIVE
    6. a real, active step is supplied
    7. campaign-lead isn't already in a stopped state
    8. no duplicate send for lead+campaign+step (idempotency)
    """
    if not valid_email(lead.email):
        return Eligibility(False, "invalid_email")

    if store.is_suppressed(lead.email):
        return Eligibility(False, "suppressed")

    if lead.unsubscribed:
        return Eligibility(False, "unsubscribed")
    if lead.bounced:
        return Eligibility(False, "bounced")
    if lead.do_not_contact:
        return Eligibility(False, "do_not_contact")

    if lead.has_replied:
        return Eligibility(False, "replied")
    if lead.meeting_booked:
        return Eligibility(False, "meeting_booked")
    if lead.is_customer:
        return Eligibility(False, "converted")

    if campaign.state is not CampaignState.ACTIVE:
        return Eligibility(False, f"campaign_{campaign.state.value}")

    if step is None:
        return Eligibility(False, "no_step_available")
    if not step.active:
        return Eligibility(False, "step_inactive")

    if campaign_lead is not None and campaign_lead.state.is_stopped():
        reason = campaign_lead.stopped_reason or campaign_lead.state.value
        return Eligibility(False, f"lead_stopped:{reason}")

    idem = f"{lead.id}:{campaign.id}:{step.id}"
    if store.has_queue_key(idem):
        return Eligibility(False, "duplicate_send")

    return Eligibility(True, "ok")
