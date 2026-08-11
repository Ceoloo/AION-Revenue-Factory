"""Send queue and worker.

Emails are never sent from a request path; they are enqueued and a worker
drains the queue. The worker is the single place that:

- re-checks eligibility + suppression at send time (state may have changed
  since enqueue),
- enforces the sending window and the daily send limits (campaign + global),
- personalizes + renders the email,
- calls the ``EmailProvider``,
- applies retry with exponential backoff, never retrying permanent failures,
- records the resulting message, event, and lead state transition.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from ..integrations import AIGateway
from .config import OutreachConfig
from .eligibility import is_lead_eligible_for_send
from .enums import EventType, LeadCampaignState, QueueStatus
from .logging import log_event, new_request_id
from .models import EmailEvent, EmailMessage, QueueItem
from .personalization import AIPersonalizer
from .providers.base import (
    EmailProvider,
    OutboundEmail,
    PermanentProviderError,
    ProviderError,
)
from .scheduling import within_sending_window
from .store import OutreachStore
from .templates import render


@dataclass
class ProcessResult:
    processed: int
    sent: int
    skipped: int
    failed: int
    reasons: dict


class QueueWorker:
    def __init__(
        self,
        store: OutreachStore,
        provider: EmailProvider,
        gateway: AIGateway,
        config: OutreachConfig,
        *,
        personalizer: Optional[AIPersonalizer] = None,
    ) -> None:
        self.store = store
        self.provider = provider
        self.config = config
        self.personalizer = personalizer or AIPersonalizer(
            gateway, store, model_name=getattr(provider, "name", "template")
        )

    # ---- limits ----
    def _daily_room(self, campaign_id: str, day_iso: str) -> tuple[int, int]:
        """Remaining sends allowed today, (global_room, campaign_room)."""
        global_sent = self.store.sends_on(day_iso)
        campaign_sent = self.store.sends_on(day_iso, campaign_id)
        campaign = self.store.get_campaign(campaign_id)
        campaign_limit = campaign.daily_send_limit if campaign else self.config.max_daily_sends
        return (
            self.config.max_daily_sends - global_sent,
            campaign_limit - campaign_sent,
        )

    def _variables(self, lead, campaign) -> dict:
        variables = {
            "first_name": lead.first_name or "there",
            "last_name": lead.last_name,
            "full_name": lead.full_name,
            "company": lead.company or "your company",
            "job_title": lead.job_title,
            "industry": lead.industry or campaign.industry,
            "offer": campaign.offer,
        }
        variables.update(self.config.default_variables())
        return variables

    def process_once(self, *, now: Optional[datetime] = None, limit: int = 100) -> ProcessResult:
        """Process due PENDING queue items. Returns a summary."""
        now = now or datetime.now(timezone.utc)
        day_iso = now.date().isoformat()
        reasons: dict[str, int] = {}
        sent = skipped = failed = processed = 0

        def bump(reason: str) -> None:
            reasons[reason] = reasons.get(reason, 0) + 1

        due = [
            item
            for item in self.store.queue_items(QueueStatus.PENDING)
            if _as_utc(item.scheduled_at) <= _as_utc(now)
        ]
        due.sort(key=lambda i: i.scheduled_at)

        for item in due:
            if processed >= limit:
                break

            # Sending window: hold (do not fail) items outside the window.
            if not within_sending_window(self.config, now):
                skipped += 1
                bump("outside_window")
                continue

            global_room, campaign_room = self._daily_room(item.campaign_id, day_iso)
            if global_room <= 0:
                skipped += 1
                bump("global_daily_limit")
                continue
            if campaign_room <= 0:
                skipped += 1
                bump("campaign_daily_limit")
                continue

            processed += 1
            outcome = self._process_item(item, now)
            if outcome == "sent":
                sent += 1
            elif outcome.startswith("skip:"):
                skipped += 1
                bump(outcome[5:])
            else:
                failed += 1
                bump(outcome)

        return ProcessResult(
            processed=processed, sent=sent, skipped=skipped, failed=failed, reasons=reasons
        )

    def _process_item(self, item: QueueItem, now: datetime) -> str:
        req = new_request_id()
        lead = self.store.get_lead(item.lead_id)
        campaign = self.store.get_campaign(item.campaign_id)
        if lead is None or campaign is None:
            item.status = QueueStatus.CANCELLED
            item.error = "missing lead or campaign"
            item.completed_at = now
            self.store.save_queue_item(item)
            return "skip:missing_entity"

        step = next((s for s in campaign.steps if s.id == item.step_id), None)
        campaign_lead = self.store.get_campaign_lead(item.campaign_id, item.lead_id)

        # Re-check eligibility at send time. NB: the idempotency portion of the
        # eligibility check would see this item's own key, so we validate the
        # business rules via the lead/campaign/suppression path here and treat a
        # duplicate-detected item as a genuine cancel.
        elig = is_lead_eligible_for_send(lead, campaign, step, _NoDupStore(self.store), campaign_lead)
        if not elig.eligible:
            item.status = QueueStatus.CANCELLED
            item.error = elig.reason
            item.completed_at = now
            self.store.save_queue_item(item)
            if campaign_lead and elig.reason in ("unsubscribed", "bounced", "suppressed"):
                campaign_lead.state = (
                    LeadCampaignState.UNSUBSCRIBED
                    if "unsub" in elig.reason
                    else LeadCampaignState.BOUNCED
                )
                self.store.save_campaign_lead(campaign_lead)
            log_event("email.cancelled", request_id=req, campaign_id=campaign.id,
                      lead_id=lead.id, queue_id=item.id, reason=elig.reason)
            return f"skip:{elig.reason}"

        # Build the email (personalize + render), guarding AI failures.
        try:
            personalization = self.personalizer.personalize(lead, campaign, step)
            variables = self._variables(lead, campaign)
            subject = render(personalization.subject, variables) if "{{" in personalization.subject else personalization.subject
            body = render(personalization.body, variables) if "{{" in personalization.body else personalization.body
        except Exception as exc:  # AI/template failure: retry, do not send broken copy
            return self._retry_or_fail(item, now, f"personalization_error:{exc}", req)

        # Test-mode redirect: preserve the real recipient in metadata.
        to_email = lead.email
        intended = ""
        if self.config.test_email_address:
            intended = lead.email
            to_email = self.config.test_email_address

        message = EmailMessage(
            campaign_id=campaign.id,
            lead_id=lead.id,
            step_id=step.id,
            to_email=to_email,
            intended_recipient=intended,
            subject=subject,
            body=body,
            from_email=self.config.email_from,
            reply_to=self.config.email_reply_to,
            provider=getattr(self.provider, "name", ""),
        )

        item.status = QueueStatus.PROCESSING
        item.attempts += 1
        item.last_attempt_at = now
        self.store.save_queue_item(item)

        try:
            result = self.provider.send_email(
                OutboundEmail(
                    to_email=to_email,
                    subject=subject,
                    body=body,
                    from_email=self.config.email_from,
                    reply_to=self.config.email_reply_to,
                    tags={"campaign_id": campaign.id, "lead_id": lead.id, "step_id": step.id,
                          "intended_recipient": intended} if intended else
                         {"campaign_id": campaign.id, "lead_id": lead.id, "step_id": step.id},
                )
            )
        except PermanentProviderError as exc:
            item.status = QueueStatus.FAILED
            item.error = f"permanent:{exc}"
            item.completed_at = now
            self.store.save_queue_item(item)
            log_event("email.failed", level="error", request_id=req, campaign_id=campaign.id,
                      lead_id=lead.id, queue_id=item.id, provider=item.provider, error=str(exc))
            return "permanent_failure"
        except ProviderError as exc:
            return self._retry_or_fail(item, now, str(exc), req)

        # Success.
        message.provider_message_id = result.provider_message_id
        message.status = result.status
        message.sent_at = result.timestamp
        self.store.save_message(message)

        item.status = QueueStatus.SENT
        item.provider = getattr(self.provider, "name", "")
        item.provider_message_id = result.provider_message_id
        item.completed_at = now
        self.store.save_queue_item(item)

        self.store.record_event(
            EmailEvent(
                event_type=EventType.EMAIL_SENT,
                lead_id=lead.id,
                campaign_id=campaign.id,
                email_id=message.id,
                provider_message_id=result.provider_message_id,
                provider=item.provider,
            )
        )

        if campaign_lead is not None:
            campaign_lead.state = LeadCampaignState.SENT
            campaign_lead.current_step = step.order
            campaign_lead.last_sent_at = result.timestamp
            campaign_lead.next_step_at = None
            self.store.save_campaign_lead(campaign_lead)

        log_event("email.sent", request_id=req, campaign_id=campaign.id, lead_id=lead.id,
                  queue_id=item.id, provider=item.provider, event_type="email_sent",
                  provider_message_id=result.provider_message_id, subject=subject[:80])
        return "sent"

    def _retry_or_fail(self, item: QueueItem, now: datetime, error: str, req: str) -> str:
        item.error = error
        if item.attempts >= self.config.max_attempts:
            item.status = QueueStatus.FAILED
            item.completed_at = now
            self.store.save_queue_item(item)
            log_event("email.failed", level="error", request_id=req, campaign_id=item.campaign_id,
                      lead_id=item.lead_id, queue_id=item.id, error=error, attempts=item.attempts)
            return "exhausted_retries"
        # Back off: base * 2^(attempts-1), scheduled into the future.
        from datetime import timedelta

        backoff = self.config.retry_base_seconds * (2 ** max(item.attempts - 1, 0))
        item.status = QueueStatus.PENDING
        item.scheduled_at = _as_utc(now) + timedelta(seconds=backoff)
        self.store.save_queue_item(item)
        log_event("email.retry", level="warning", request_id=req, campaign_id=item.campaign_id,
                  lead_id=item.lead_id, queue_id=item.id, error=error, attempts=item.attempts,
                  backoff_seconds=backoff)
        return f"skip:retry_scheduled"


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class _NoDupStore:
    """Wraps a store so the duplicate-send check is bypassed at *send* time.

    At enqueue time the idempotency key must be unique. At processing time the
    item's own key is already present, so we must not let that read as a
    duplicate — every other store method delegates unchanged.
    """

    def __init__(self, inner: OutreachStore) -> None:
        self._inner = inner

    def has_queue_key(self, idempotency_key: str) -> bool:
        return False

    def __getattr__(self, name):
        return getattr(self._inner, name)
