from datetime import datetime, timezone

import pytest

from aion_revenue_factory.outreach import (
    Campaign,
    CampaignState,
    Lead,
    OutreachConfig,
    OutreachSystem,
    QueueStatus,
)
from aion_revenue_factory.outreach.leads_source import lead_from_airtable
from aion_revenue_factory.outreach.providers.base import (
    OutboundEmail,
    PermanentProviderError,
    ProviderError,
    SendResult,
)

from .conftest import IN_WINDOW


class _FlakyProvider:
    name = "flaky"
    cost_per_email = 0.0

    def __init__(self, fail_times):
        self.fail_times = fail_times
        self.calls = 0

    def send_email(self, email):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise ProviderError("temporary")
        return SendResult(provider_message_id="ok_1", status="sent",
                          timestamp=datetime.now(timezone.utc))

    def get_delivery_status(self, x):
        return "unknown"

    def parse_webhook(self, h, b):
        return []

    def validate_configuration(self):
        from aion_revenue_factory.outreach.providers.base import ConfigStatus
        return ConfigStatus(True, "")


class _PermanentProvider(_FlakyProvider):
    def send_email(self, email):
        raise PermanentProviderError("rejected recipient")


def _system_with(provider, **cfg):
    config = OutreachConfig(dry_run=False, email_provider="console", email_from="s@aion.example",
                            default_timezone="UTC", **cfg)
    system = OutreachSystem(config, provider=provider)
    return system


def _campaign_lead(system):
    c = Campaign(name="c", state=CampaignState.DRAFT, industry="X", offer="O")
    c.add_step(delay_days=0, subject="s {{company}}", body_template="b {{first_name}}")
    lead = Lead(first_name="A", company="Acme", email="a@acme.example", icp_score=80)
    system.engine.create_campaign(c)
    system.engine.add_lead(c, lead)
    system.engine.activate(c)
    return c, lead


def test_transient_failure_retries_then_sends():
    provider = _FlakyProvider(fail_times=1)
    system = _system_with(provider, max_attempts=3, retry_base_seconds=1.0)
    c, lead = _campaign_lead(system)
    system.engine.enqueue_due(c, now=IN_WINDOW)

    # First pass: fails, reschedules for retry (still PENDING, future scheduled_at).
    r1 = system.worker.process_once(now=IN_WINDOW)
    assert r1.sent == 0
    item = system.store.queue_items()[0]
    assert item.status is QueueStatus.PENDING
    assert item.attempts == 1

    # Second pass after backoff window: succeeds.
    later = item.scheduled_at
    r2 = system.worker.process_once(now=later)
    assert r2.sent == 1
    assert system.store.queue_items()[0].status is QueueStatus.SENT


def test_permanent_failure_not_retried():
    provider = _PermanentProvider(fail_times=99)
    system = _system_with(provider, max_attempts=5)
    c, lead = _campaign_lead(system)
    system.engine.enqueue_due(c, now=IN_WINDOW)
    result = system.worker.process_once(now=IN_WINDOW)
    assert result.failed == 1
    item = system.store.queue_items()[0]
    assert item.status is QueueStatus.FAILED
    assert item.attempts == 1  # no further attempts


def test_retries_exhaust_to_failed():
    provider = _FlakyProvider(fail_times=99)
    system = _system_with(provider, max_attempts=2, retry_base_seconds=1.0)
    c, lead = _campaign_lead(system)
    system.engine.enqueue_due(c, now=IN_WINDOW)
    system.worker.process_once(now=IN_WINDOW)  # attempt 1 -> retry
    item = system.store.queue_items()[0]
    system.worker.process_once(now=item.scheduled_at)  # attempt 2 -> exhausted
    assert system.store.queue_items()[0].status is QueueStatus.FAILED


def test_config_from_env_defaults_safe():
    cfg = OutreachConfig.from_env({})
    assert cfg.dry_run is True
    assert cfg.max_daily_sends == 100
    assert cfg.email_provider == "console"


def test_config_from_env_reads_values():
    cfg = OutreachConfig.from_env({
        "OUTREACH_DRY_RUN": "false",
        "MAX_DAILY_SENDS": "25",
        "RESEND_API_KEY": "re_x",
        "EMAIL_FROM": "go@aion.example",
        "DEFAULT_TIMEZONE": "America/New_York",
    })
    assert cfg.dry_run is False
    assert cfg.max_daily_sends == 25
    assert cfg.email_provider == "resend"
    assert cfg.email_from == "go@aion.example"


def test_lead_from_airtable_mapping():
    record = {
        "id": "recABC",
        "fields": {
            "First Name": "Dana", "Company": "Voltify", "Email": "dana@voltify.example",
            "ICP Score": 88, "Unsubscribed": True, "Bounce Status": "Bounced",
        },
    }
    lead = lead_from_airtable(record)
    assert lead.first_name == "Dana"
    assert lead.airtable_id == "recABC"
    assert lead.icp_score == 88.0
    assert lead.unsubscribed is True
    assert lead.bounced is True
