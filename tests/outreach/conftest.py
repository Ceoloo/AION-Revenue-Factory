"""Shared fixtures for outreach tests."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aion_revenue_factory.outreach import (
    Campaign,
    CampaignState,
    Lead,
    OutreachConfig,
    OutreachSystem,
)


# A weekday inside the default 08:30-16:30 window (Wed 2026-08-12 10:00 UTC).
IN_WINDOW = datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def config() -> OutreachConfig:
    return OutreachConfig(
        dry_run=True,
        email_from="sales@aion.example",
        email_reply_to="reply@aion.example",
        default_timezone="UTC",
        max_daily_sends=100,
    )


@pytest.fixture
def system(config: OutreachConfig) -> OutreachSystem:
    return OutreachSystem(config)


@pytest.fixture
def lead() -> Lead:
    return Lead(
        first_name="Dana",
        last_name="Owner",
        company="Voltify Contractors",
        job_title="Owner",
        email="dana@voltify.example",
        industry="Electrical Contracting",
        icp_score=80.0,
    )


@pytest.fixture
def campaign() -> Campaign:
    c = Campaign(
        name="Test Campaign",
        industry="Electrical Contracting",
        offer="Sales Conversion Audit",
        daily_send_limit=50,
        state=CampaignState.DRAFT,
    )
    c.add_step(
        delay_days=0,
        subject="hello {{company}}",
        body_template="Hi {{first_name}}, about {{offer}}. — {{sender_name}}",
    )
    c.add_step(
        delay_days=3,
        subject="follow up {{company}}",
        body_template="Hi {{first_name}}, circling back. — {{sender_name}}",
    )
    return c
