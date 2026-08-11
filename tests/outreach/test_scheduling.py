from datetime import datetime, timezone

from aion_revenue_factory.outreach import OutreachConfig, SendingWindow
from aion_revenue_factory.outreach.scheduling import (
    next_send_time,
    step_scheduled_at,
    within_sending_window,
)


def _cfg(tz="UTC"):
    return OutreachConfig(default_timezone=tz, window=SendingWindow())


def test_within_window_weekday_midday():
    cfg = _cfg()
    assert within_sending_window(cfg, datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc))


def test_outside_window_evening():
    cfg = _cfg()
    assert not within_sending_window(cfg, datetime(2026, 8, 12, 20, 0, tzinfo=timezone.utc))


def test_weekend_blocked():
    cfg = _cfg()
    # 2026-08-15 is a Saturday
    assert not within_sending_window(cfg, datetime(2026, 8, 15, 10, 0, tzinfo=timezone.utc))


def test_next_send_time_snaps_forward_from_evening():
    cfg = _cfg()
    evening = datetime(2026, 8, 12, 20, 0, tzinfo=timezone.utc)  # Wed 20:00
    nxt = next_send_time(cfg, evening)
    assert within_sending_window(cfg, nxt)
    assert nxt > evening
    # should be the next morning at window start (08:30)
    assert nxt.date() == datetime(2026, 8, 13).date()
    assert (nxt.hour, nxt.minute) == (8, 30)


def test_next_send_time_saturday_goes_to_monday():
    cfg = _cfg()
    sat = datetime(2026, 8, 15, 10, 0, tzinfo=timezone.utc)
    nxt = next_send_time(cfg, sat)
    assert nxt.weekday() == 0  # Monday
    assert within_sending_window(cfg, nxt)


def test_step_delay_applied():
    cfg = _cfg()

    class Step:
        delay_days = 3

    prev = datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)  # Wed
    scheduled = step_scheduled_at(cfg, Step(), previous_sent_at=prev, now=prev)
    # 3 days later is Saturday -> should land on/after the following Monday
    assert scheduled.weekday() == 0
    assert scheduled >= prev
