"""The ``EmailProvider`` abstraction.

The campaign engine speaks *only* this interface, so swapping Resend for SES (or
anything else) is configuration, not code. Every provider offers the same four
conceptual operations from the spec:

- ``send_email``            -> SendResult(provider_message_id, status, timestamp)
- ``get_delivery_status``   -> a normalized status string
- ``parse_webhook``         -> normalized provider events (handleWebhook)
- ``validate_configuration``-> ConfigStatus(ok, detail)

Plus a declared ``cost_per_email`` for the cost/ROI model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Protocol, runtime_checkable

from ..enums import EventType


class ProviderError(RuntimeError):
    """Raised for a transient provider failure that is worth retrying."""


class PermanentProviderError(ProviderError):
    """A failure that must NOT be retried (bad recipient, rejected content)."""


@dataclass(frozen=True)
class OutboundEmail:
    """What the worker hands a provider to send."""

    to_email: str
    subject: str
    body: str
    from_email: str
    reply_to: str = ""
    # Correlates the send back to our records; providers echo it where possible.
    tags: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SendResult:
    provider_message_id: str
    status: str  # "sent" | "queued" | "dry_run"
    timestamp: datetime
    detail: str = ""


@dataclass(frozen=True)
class ConfigStatus:
    ok: bool
    detail: str = ""


@dataclass(frozen=True)
class NormalizedEvent:
    """A provider webhook event mapped onto our internal vocabulary."""

    event_type: EventType
    provider_message_id: str
    email: str = ""
    timestamp: Optional[datetime] = None
    metadata: dict = field(default_factory=dict)


@runtime_checkable
class EmailProvider(Protocol):
    name: str
    cost_per_email: float

    def send_email(self, email: OutboundEmail) -> SendResult: ...
    def get_delivery_status(self, provider_message_id: str) -> str: ...
    def parse_webhook(self, headers: dict, body: bytes) -> list[NormalizedEvent]: ...
    def validate_configuration(self) -> ConfigStatus: ...
