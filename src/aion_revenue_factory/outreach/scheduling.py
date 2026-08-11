"""Schedule calculation and sending-window enforcement.

All timestamps are stored and reasoned about in UTC. The sending-window check
converts to the configured (or lead's) local timezone before deciding whether a
moment is inside the allowed window — never on raw server UTC.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .config import OutreachConfig
from .models import CampaignStep


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def within_sending_window(config: OutreachConfig, when_utc: datetime) -> bool:
    """True if ``when_utc`` falls inside the allowed local sending window."""
    local = config.to_local(_as_utc(when_utc))
    return config.window.allows(local)


def next_send_time(config: OutreachConfig, not_before_utc: datetime) -> datetime:
    """The earliest UTC instant >= ``not_before_utc`` inside the window.

    Converts to local, snaps to the next open window locally, converts back to
    UTC. Guarantees we never schedule outside Mon-Fri 08:30-16:30 (by default).
    """
    base_utc = _as_utc(not_before_utc)
    local = config.to_local(base_utc)
    opened_local = config.window.next_open(local)
    # opened_local carries local tzinfo when zoneinfo is available.
    if opened_local.tzinfo is None:
        return opened_local.replace(tzinfo=timezone.utc)
    return opened_local.astimezone(timezone.utc)


def step_scheduled_at(
    config: OutreachConfig,
    step: CampaignStep,
    *,
    previous_sent_at: datetime | None,
    now: datetime | None = None,
) -> datetime:
    """When step ``step`` should be sent.

    Step 1 (no previous send) is scheduled at the next open window from ``now``.
    Later steps are ``delay_days`` after the previous step's send, then snapped
    forward into the next open window.
    """
    now = _as_utc(now or datetime.now(timezone.utc))
    if previous_sent_at is None:
        earliest = now
    else:
        earliest = _as_utc(previous_sent_at) + timedelta(days=step.delay_days)
        if earliest < now:
            earliest = now
    return next_send_time(config, earliest)
