"""Campaign metrics and revenue attribution.

Computes the funnel rates and ROI from the outreach store. ROI follows the spec:

    ROI = (revenue - campaign_cost) / campaign_cost

and when cost data is missing/zero it returns the sentinel string
``"Not enough cost data"`` rather than a misleading infinite ROI.

Campaign cost is the *actual* variable cost (emails sent x provider
cost-per-email + AI generations x cost-per-generation) plus the campaign's
externally-tracked fixed cost.
"""

from __future__ import annotations

from .costs import CampaignCosts, DEFAULT_GENERATION_COST
from .enums import EventType, LeadCampaignState
from .models import Campaign
from .store import OutreachStore

_NO_COST = "Not enough cost data"


def _rate(numer: int, denom: int) -> float:
    return round(numer / denom, 4) if denom else 0.0


class OutreachDashboard:
    def __init__(self, store: OutreachStore, *, cost_per_email: float, cost_per_generation: float = DEFAULT_GENERATION_COST) -> None:
        self.store = store
        self.cost_per_email = cost_per_email
        self.cost_per_generation = cost_per_generation

    def campaign_metrics(self, campaign: Campaign) -> dict:
        leads = self.store.campaign_leads(campaign.id)
        total_leads = len(leads)

        # Emails actually sent for this campaign (from the event stream).
        sent_events = [
            e for e in self.store.events()
            if e.campaign_id == campaign.id and e.event_type is EventType.EMAIL_SENT
        ]
        emails_sent = len(sent_events)
        # Leads that received at least one send (the funnel base).
        sent_lead_ids = {e.lead_id for e in sent_events if e.lead_id}
        contacted = len(sent_lead_ids)

        delivered = sum(
            1 for e in self.store.events()
            if e.campaign_id == campaign.id and e.event_type is EventType.EMAIL_DELIVERED
        )
        bounced = sum(
            1 for e in self.store.events()
            if e.campaign_id == campaign.id and e.event_type is EventType.EMAIL_BOUNCED
        )

        replied = sum(1 for cl in leads if cl.state is LeadCampaignState.REPLIED or cl.positive_reply or cl.stopped_reason == "replied")
        positive = sum(1 for cl in leads if cl.positive_reply)
        meetings = sum(1 for cl in leads if cl.state is LeadCampaignState.MEETING_BOOKED or cl.stopped_reason == "meeting_booked")
        opportunities = sum(1 for cl in leads if cl.opportunity)
        converted = sum(1 for cl in leads if cl.state is LeadCampaignState.CONVERTED)
        revenue = round(sum(cl.revenue for cl in leads), 2)

        generations = sum(
            1 for g in getattr(self.store, "generations", list)()  # type: ignore[operator]
            if g.campaign_id == campaign.id
        ) if hasattr(self.store, "generations") else emails_sent

        costs = CampaignCosts(
            emails_sent=emails_sent,
            generations=generations,
            cost_per_email=self.cost_per_email,
            cost_per_generation=self.cost_per_generation,
            fixed_cost=campaign.campaign_cost,
        )
        total_cost = costs.total

        return {
            "campaign_id": campaign.id,
            "name": campaign.name,
            "state": campaign.state.value,
            "total_leads": total_leads,
            "emails_sent": emails_sent,
            "contacted": contacted,
            "delivered": delivered,
            "bounced": bounced,
            "replies": replied,
            "positive_replies": positive,
            "meetings": meetings,
            "opportunities": opportunities,
            "converted": converted,
            "revenue": revenue,
            # rates (denominator = leads contacted)
            "delivery_rate": _rate(delivered, emails_sent),
            "bounce_rate": _rate(bounced, emails_sent),
            "reply_rate": _rate(replied, contacted),
            "positive_reply_rate": _rate(positive, contacted),
            "meeting_rate": _rate(meetings, contacted),
            "opportunity_rate": _rate(opportunities, contacted),
            "close_rate": _rate(converted, contacted),
            "revenue_per_lead": round(revenue / total_leads, 2) if total_leads else 0.0,
            "revenue_per_email": round(revenue / emails_sent, 2) if emails_sent else 0.0,
            # cost / ROI
            "email_cost": costs.email_cost,
            "ai_cost": costs.ai_cost,
            "fixed_cost": campaign.campaign_cost,
            "total_cost": total_cost,
            "roi": self._roi(revenue, total_cost),
        }

    def overview(self) -> dict:
        """Aggregate metrics across every campaign."""
        per = [self.campaign_metrics(c) for c in self.store.campaigns()]
        total_leads = sum(m["total_leads"] for m in per)
        emails_sent = sum(m["emails_sent"] for m in per)
        contacted = sum(m["contacted"] for m in per)
        delivered = sum(m["delivered"] for m in per)
        bounced = sum(m["bounced"] for m in per)
        replies = sum(m["replies"] for m in per)
        positive = sum(m["positive_replies"] for m in per)
        meetings = sum(m["meetings"] for m in per)
        opportunities = sum(m["opportunities"] for m in per)
        revenue = round(sum(m["revenue"] for m in per), 2)
        total_cost = round(sum(m["total_cost"] for m in per), 4)
        return {
            "total_leads": total_leads,
            "emails_sent": emails_sent,
            "delivered": delivered,
            "bounce_rate": _rate(bounced, emails_sent),
            "reply_rate": _rate(replies, contacted),
            "positive_reply_rate": _rate(positive, contacted),
            "meetings": meetings,
            "opportunities": opportunities,
            "revenue": revenue,
            "total_cost": total_cost,
            "roi": self._roi(revenue, total_cost),
            "campaigns": per,
        }

    @staticmethod
    def _roi(revenue: float, cost: float):
        if not cost or cost <= 0:
            return _NO_COST
        return round((revenue - cost) / cost, 4)
