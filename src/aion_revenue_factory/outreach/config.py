"""Environment-driven configuration for the Outreach Engine.

Everything operationally dangerous (sending volume, whether real emails go out,
who they go to) is controlled here and defaults to the *safe* value:

- ``OUTREACH_DRY_RUN`` defaults to **true** — no real emails without opting in.
- ``MAX_DAILY_SENDS`` defaults to a conservative 100.
- The sending window defaults to Mon-Fri, 08:30-16:30.

No secrets are stored on disk; they are read from the environment on demand.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

try:  # Python 3.9+
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - supported floor is 3.10
    ZoneInfo = None  # type: ignore


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _parse_hhmm(value: str, fallback: time) -> time:
    try:
        hh, mm = value.strip().split(":")
        return time(int(hh), int(mm))
    except (ValueError, AttributeError):
        return fallback


# 0 = Monday .. 6 = Sunday (matches datetime.weekday()).
_DEFAULT_DAYS = frozenset({0, 1, 2, 3, 4})
_DEFAULT_START = time(8, 30)
_DEFAULT_END = time(16, 30)


@dataclass(frozen=True)
class SendingWindow:
    """Allowed local send times. Timestamps are stored UTC; conversion for the
    window check uses the configured timezone (or a lead's timezone when known).
    """

    days: frozenset[int] = _DEFAULT_DAYS
    start: time = _DEFAULT_START
    end: time = _DEFAULT_END

    def allows(self, local_dt: datetime) -> bool:
        if local_dt.weekday() not in self.days:
            return False
        return self.start <= local_dt.time() <= self.end

    def next_open(self, local_dt: datetime) -> datetime:
        """The earliest local time at/after ``local_dt`` inside the window."""
        candidate = local_dt
        for _ in range(0, 14):  # at most two weeks out; guarantees termination
            if candidate.weekday() in self.days:
                if candidate.time() < self.start:
                    return candidate.replace(
                        hour=self.start.hour,
                        minute=self.start.minute,
                        second=0,
                        microsecond=0,
                    )
                if self.start <= candidate.time() <= self.end:
                    return candidate
            # advance to start-of-window next day
            nxt = (candidate + timedelta(days=1)).replace(
                hour=self.start.hour, minute=self.start.minute, second=0, microsecond=0
            )
            candidate = nxt
        return candidate


@dataclass
class OutreachConfig:
    app_env: str = "development"
    dry_run: bool = True
    test_email_address: str = ""
    max_daily_sends: int = 100
    default_timezone: str = "UTC"
    email_provider: str = "console"  # console | resend | ses
    email_from: str = "outreach@example.com"
    email_reply_to: str = ""
    sender_name: str = "AION"
    sender_company: str = "AION Systems"
    booking_link: str = ""
    resend_api_key: str = ""
    resend_webhook_secret: str = ""
    log_level: str = "INFO"
    window: SendingWindow = field(default_factory=SendingWindow)
    # Retry policy
    max_attempts: int = 3
    retry_base_seconds: float = 60.0
    # Multi-worker: a claimed item whose worker went silent this long is
    # reclaimed (returned to PENDING) by the next worker cycle.
    claim_stale_seconds: float = 900.0

    @classmethod
    def from_env(cls, env: dict | None = None) -> "OutreachConfig":
        env = os.environ if env is None else env

        window = SendingWindow(
            start=_parse_hhmm(env.get("OUTREACH_WINDOW_START", ""), _DEFAULT_START),
            end=_parse_hhmm(env.get("OUTREACH_WINDOW_END", ""), _DEFAULT_END),
        )

        # Provider selection: explicit EMAIL_PROVIDER wins; otherwise infer from
        # credentials; otherwise the safe offline console provider. Dry-run also
        # forces console so real credentials can be present without sending.
        provider = env.get("EMAIL_PROVIDER", "").strip().lower()
        if not provider:
            provider = "resend" if env.get("RESEND_API_KEY") else "console"

        return cls(
            app_env=env.get("APP_ENV", "development"),
            dry_run=_as_bool(env.get("OUTREACH_DRY_RUN"), True),
            test_email_address=env.get("TEST_EMAIL_ADDRESS", ""),
            max_daily_sends=int(env.get("MAX_DAILY_SENDS", "100") or "100"),
            default_timezone=env.get("DEFAULT_TIMEZONE", "UTC"),
            email_provider=provider,
            email_from=env.get("EMAIL_FROM", "outreach@example.com"),
            email_reply_to=env.get("EMAIL_REPLY_TO", ""),
            sender_name=env.get("OUTREACH_SENDER_NAME", "AION"),
            sender_company=env.get("OUTREACH_SENDER_COMPANY", "AION Systems"),
            booking_link=env.get("OUTREACH_BOOKING_LINK", ""),
            resend_api_key=env.get("RESEND_API_KEY", ""),
            resend_webhook_secret=env.get("RESEND_WEBHOOK_SECRET", ""),
            log_level=env.get("LOG_LEVEL", "INFO"),
            window=window,
            max_attempts=int(env.get("OUTREACH_MAX_ATTEMPTS", "3") or "3"),
            retry_base_seconds=float(env.get("OUTREACH_RETRY_BASE_SECONDS", "60") or "60"),
            claim_stale_seconds=float(env.get("OUTREACH_CLAIM_STALE_SECONDS", "900") or "900"),
        )

    def tzinfo(self):
        """Return the configured tzinfo, falling back to UTC if unavailable."""
        if ZoneInfo is None:
            return None
        try:
            return ZoneInfo(self.default_timezone)
        except Exception:  # unknown tz name -> UTC
            try:
                return ZoneInfo("UTC")
            except Exception:  # pragma: no cover
                return None

    def to_local(self, utc_dt: datetime):
        """Convert a naive/aware UTC datetime to configured local time."""
        tz = self.tzinfo()
        if tz is None:
            return utc_dt
        from datetime import timezone

        if utc_dt.tzinfo is None:
            utc_dt = utc_dt.replace(tzinfo=timezone.utc)
        return utc_dt.astimezone(tz)

    def default_variables(self) -> dict:
        """Template variables that come from sender configuration."""
        return {
            "sender_name": self.sender_name,
            "sender_company": self.sender_company,
            "booking_link": self.booking_link,
        }
