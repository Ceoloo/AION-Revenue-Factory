"""Amazon SES provider — V1 stub.

Intentionally NOT implemented for V1. It exists to prove the abstraction: the
campaign engine, queue, eligibility, and webhook-normalization layers are all
written against :class:`EmailProvider`, so bringing SES online is a
configuration change (``EMAIL_PROVIDER=ses`` + AWS credentials) plus filling in
the three TODOs below — no campaign logic changes.

Migration notes (see docs/AION-OUTREACH-SETUP.md §"Migrating from Resend to SES"):

- ``send_email`` -> call SES ``SendEmail`` / ``SendEmailV2`` (via boto3 or a
  SigV4-signed HTTPS request to keep the stdlib-only footprint) and return the
  SES ``MessageId`` as ``provider_message_id``.
- Delivery/bounce/complaint arrive as SNS notifications, not direct webhooks;
  ``parse_webhook`` should confirm the SNS subscription, verify the SNS
  signature, and map ``Bounce``/``Complaint``/``Delivery`` onto the same
  internal ``EMAIL_BOUNCED``/``EMAIL_COMPLAINT``/``EMAIL_DELIVERED`` events the
  rest of the system already understands.
- ``validate_configuration`` -> check credentials + a verified sending identity.
"""

from __future__ import annotations

from ..costs import DEFAULT_SES_COST_PER_EMAIL
from .base import (
    ConfigStatus,
    EmailProvider,
    NormalizedEvent,
    OutboundEmail,
    SendResult,
)


class AmazonSESProvider(EmailProvider):
    name = "ses"

    def __init__(
        self,
        *,
        region: str = "us-east-1",
        cost_per_email: float = DEFAULT_SES_COST_PER_EMAIL,
    ) -> None:
        self.region = region
        self.cost_per_email = cost_per_email

    def send_email(self, email: OutboundEmail) -> SendResult:  # pragma: no cover
        raise NotImplementedError(
            "AmazonSESProvider is a V1 stub. Set EMAIL_PROVIDER=resend, or "
            "implement SES per docs/AION-OUTREACH-SETUP.md before enabling it."
        )

    def get_delivery_status(self, provider_message_id: str) -> str:  # pragma: no cover
        return "unknown"

    def parse_webhook(self, headers: dict, body: bytes) -> list[NormalizedEvent]:  # pragma: no cover
        # TODO: verify SNS signature and map Bounce/Complaint/Delivery.
        return []

    def validate_configuration(self) -> ConfigStatus:
        return ConfigStatus(False, "AmazonSESProvider is a stub and not enabled in V1")
