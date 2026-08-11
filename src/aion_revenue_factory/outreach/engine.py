"""The campaign engine.

Owns campaign lifecycle, lead segmentation/membership, and turning "due" steps
into queue items. It never sends — it enqueues, and the worker drains the queue.
Every decision to enqueue passes through the *one* canonical eligibility gate.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional

from .eligibility import is_lead_eligible_for_send
from .enums import CampaignState, LeadCampaignState
from .logging import log_event
from .models import Campaign, CampaignLead, CampaignStep, Lead, QueueItem
from .scheduling import step_scheduled_at
from .config import OutreachConfig
from .store import OutreachStore


class CampaignEngine:
    def __init__(self, store: OutreachStore, config: OutreachConfig) -> None:
        self.store = store
        self.config = config

    # ---- campaign lifecycle ----
    def create_campaign(self, campaign: Campaign) -> Campaign:
        self.store.save_campaign(campaign)
        log_event("campaign.created", campaign_id=campaign.id, name=campaign.name)
        return campaign

    def _set_state(self, campaign: Campaign, state: CampaignState, event: str) -> Campaign:
        campaign.state = state
        self.store.save_campaign(campaign)
        log_event(event, campaign_id=campaign.id, state=state.value)
        return campaign

    def activate(self, campaign: Campaign) -> Campaign:
        """Launch a campaign. Requires at least one active step."""
        if not campaign.active_steps():
            raise ValueError("cannot activate a campaign with no active steps")
        return self._set_state(campaign, CampaignState.ACTIVE, "campaign.started")

    def pause(self, campaign: Campaign) -> Campaign:
        # Cancel PENDING queue items so nothing goes out while paused.
        self._cancel_pending(campaign.id, "campaign_paused")
        return self._set_state(campaign, CampaignState.PAUSED, "campaign.paused")

    def resume(self, campaign: Campaign) -> Campaign:
        return self._set_state(campaign, CampaignState.ACTIVE, "campaign.resumed")

    def stop(self, campaign: Campaign) -> Campaign:
        self._cancel_pending(campaign.id, "campaign_stopped")
        return self._set_state(campaign, CampaignState.COMPLETED, "campaign.stopped")

    def archive(self, campaign: Campaign) -> Campaign:
        return self._set_state(campaign, CampaignState.ARCHIVED, "campaign.archived")

    def _cancel_pending(self, campaign_id: str, reason: str) -> int:
        from .enums import QueueStatus

        cancelled = 0
        for item in self.store.queue_items(QueueStatus.PENDING):
            if item.campaign_id != campaign_id:
                continue
            item.status = QueueStatus.CANCELLED
            item.error = reason
            item.completed_at = datetime.now(timezone.utc)
            self.store.save_queue_item(item)
            cancelled += 1
        return cancelled

    # ---- leads / segmentation ----
    def add_lead(self, campaign: Campaign, lead: Lead) -> CampaignLead:
        """Enroll a lead. Idempotent per (campaign, lead)."""
        self.store.save_lead(lead)
        existing = self.store.get_campaign_lead(campaign.id, lead.id)
        if existing is not None:
            return existing
        cl = CampaignLead(campaign_id=campaign.id, lead_id=lead.id)
        self.store.save_campaign_lead(cl)
        log_event("campaign.lead_added", campaign_id=campaign.id, lead_id=lead.id)
        return cl

    def add_leads(self, campaign: Campaign, leads: Iterable[Lead]) -> list[CampaignLead]:
        return [self.add_lead(campaign, lead) for lead in leads]

    @staticmethod
    def segment(
        leads: Iterable[Lead],
        *,
        icp_min: float = 0.0,
        industries: Optional[Iterable[str]] = None,
    ) -> list[Lead]:
        """Filter leads into a campaign audience by ICP score and/or industry."""
        wanted = {i.lower() for i in industries} if industries else None
        out = []
        for lead in leads:
            if lead.icp_score < icp_min:
                continue
            if wanted is not None and lead.industry.lower() not in wanted:
                continue
            out.append(lead)
        return out

    # ---- revenue-attribution transitions ----
    def mark_reply(self, campaign_id: str, lead_id: str, *, positive: bool = False) -> None:
        """Record a reply (a hard stop condition) and, optionally, that it was positive."""
        lead = self.store.get_lead(lead_id)
        if lead is not None:
            lead.has_replied = True
            self.store.save_lead(lead)
        cl = self.store.get_campaign_lead(campaign_id, lead_id)
        if cl is not None:
            cl.positive_reply = cl.positive_reply or positive
        self.stop_lead(campaign_id, lead_id, LeadCampaignState.REPLIED, "replied")

    def mark_meeting(self, campaign_id: str, lead_id: str) -> None:
        lead = self.store.get_lead(lead_id)
        if lead is not None:
            lead.meeting_booked = True
            self.store.save_lead(lead)
        self.stop_lead(campaign_id, lead_id, LeadCampaignState.MEETING_BOOKED, "meeting_booked")

    def mark_opportunity(self, campaign_id: str, lead_id: str) -> None:
        cl = self.store.get_campaign_lead(campaign_id, lead_id)
        if cl is not None:
            cl.opportunity = True
            self.store.save_campaign_lead(cl)

    def mark_converted(self, campaign_id: str, lead_id: str, revenue: float = 0.0) -> None:
        lead = self.store.get_lead(lead_id)
        if lead is not None:
            lead.is_customer = True
            self.store.save_lead(lead)
        cl = self.store.get_campaign_lead(campaign_id, lead_id)
        if cl is not None:
            cl.opportunity = True
            cl.revenue = revenue
            self.store.save_campaign_lead(cl)
        self.stop_lead(campaign_id, lead_id, LeadCampaignState.CONVERTED, "converted")

    def unsubscribe(self, campaign_id: str, lead_id: str) -> None:
        from .enums import SuppressionReason
        from .suppression import SuppressionService

        lead = self.store.get_lead(lead_id)
        if lead is not None:
            lead.unsubscribed = True
            self.store.save_lead(lead)
            SuppressionService(self.store).add(lead.email, SuppressionReason.UNSUBSCRIBED)
        self.stop_lead(campaign_id, lead_id, LeadCampaignState.UNSUBSCRIBED, "unsubscribed")

    # ---- stop conditions (delegated to the canonical states) ----
    def stop_lead(self, campaign_id: str, lead_id: str, state: LeadCampaignState, reason: str) -> None:
        cl = self.store.get_campaign_lead(campaign_id, lead_id)
        if cl is None:
            return
        cl.state = state
        cl.stopped_reason = reason
        self.store.save_campaign_lead(cl)
        # Cancel any still-pending sends for this lead in this campaign.
        from .enums import QueueStatus

        for item in self.store.queue_items(QueueStatus.PENDING):
            if item.campaign_id == campaign_id and item.lead_id == lead_id:
                item.status = QueueStatus.CANCELLED
                item.error = reason
                item.completed_at = datetime.now(timezone.utc)
                self.store.save_queue_item(item)
        log_event("lead.stopped", campaign_id=campaign_id, lead_id=lead_id, reason=reason)

    # ---- scheduling / enqueue ----
    def _next_step_for(self, campaign: Campaign, cl: CampaignLead) -> Optional[CampaignStep]:
        """The next active step to send this lead, or None if the sequence is done."""
        active = sorted(campaign.active_steps(), key=lambda s: s.order)
        for step in active:
            if step.order > cl.current_step:
                return step
        return None

    def enqueue_due(self, campaign: Campaign, *, now: Optional[datetime] = None) -> list[QueueItem]:
        """Enqueue the next due step for every eligible lead in the campaign."""
        now = now or datetime.now(timezone.utc)
        created: list[QueueItem] = []

        if campaign.state is not CampaignState.ACTIVE:
            return created

        for cl in self.store.campaign_leads(campaign.id):
            if cl.state.is_stopped():
                continue
            lead = self.store.get_lead(cl.lead_id)
            if lead is None:
                continue
            step = self._next_step_for(campaign, cl)
            if step is None:
                continue

            elig = is_lead_eligible_for_send(lead, campaign, step, self.store, cl)
            if not elig.eligible:
                # Duplicate just means it's already queued — not an error.
                if elig.reason != "duplicate_send":
                    log_event("email.skipped", campaign_id=campaign.id, lead_id=lead.id,
                              reason=elig.reason)
                continue

            scheduled_at = step_scheduled_at(
                self.config, step, previous_sent_at=cl.last_sent_at, now=now
            )
            item = QueueItem(
                campaign_id=campaign.id,
                lead_id=lead.id,
                step_id=step.id,
                scheduled_at=scheduled_at,
                provider=self.config.email_provider,
            )
            if self.store.enqueue(item):
                cl.state = LeadCampaignState.SCHEDULED
                cl.next_step_at = scheduled_at
                self.store.save_campaign_lead(cl)
                created.append(item)
                log_event("email.queued", campaign_id=campaign.id, lead_id=lead.id,
                          queue_id=item.id, event_type="email_queued",
                          scheduled_at=scheduled_at.isoformat())
        return created
