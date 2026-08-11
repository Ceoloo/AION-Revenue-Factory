"""Console / dry-run email provider.

The safe default. It never contacts a network: it records what *would* have been
sent and returns a synthetic ``dry_run`` message id. This backs both
``OUTREACH_DRY_RUN=true`` and offline tests, so the whole pipeline (queue,
eligibility, personalization, state transitions) runs end-to-end with zero risk
of a real email leaving the building.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from ..enums import EventType
from .base import (
    ConfigStatus,
    EmailProvider,
    NormalizedEvent,
    OutboundEmail,
    SendResult,
)


class ConsoleProvider(EmailProvider):
    name = "console"

    def __init__(self, *, cost_per_email: float = 0.0) -> None:
        self.cost_per_email = cost_per_email
        # Inspectable record of intended sends (used by dry-run reporting/tests).
        self.outbox: list[OutboundEmail] = []

    def send_email(self, email: OutboundEmail) -> SendResult:
        self.outbox.append(email)
        return SendResult(
            provider_message_id=f"dry_{uuid.uuid4().hex[:12]}",
            status="dry_run",
            timestamp=datetime.now(timezone.utc),
            detail=f"[dry-run] would send to {email.to_email}: {email.subject!r}",
        )

    def get_delivery_status(self, provider_message_id: str) -> str:
        return "dry_run"

    def parse_webhook(self, headers: dict, body: bytes) -> list[NormalizedEvent]:
        # No real webhooks in dry-run; nothing to normalize.
        return []

    def validate_configuration(self) -> ConfigStatus:
        return ConfigStatus(True, "console provider (dry-run) is always ready")
