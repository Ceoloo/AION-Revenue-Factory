"""Resend email provider (V1). Standard library only.

Sends via the documented Resend REST API and verifies inbound webhooks using
Resend's Svix signing scheme (HMAC-SHA256), so no state changes on an unsigned
or forged payload.

Credentials come from the environment (``RESEND_API_KEY``,
``RESEND_WEBHOOK_SECRET``) — never hardcoded, never logged.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone

from ..costs import DEFAULT_RESEND_COST_PER_EMAIL
from ..enums import EventType
from .base import (
    ConfigStatus,
    EmailProvider,
    NormalizedEvent,
    OutboundEmail,
    PermanentProviderError,
    ProviderError,
    SendResult,
)

_API_URL = "https://api.resend.com/emails"

# Resend event type -> our internal event type.
_EVENT_MAP = {
    "email.sent": EventType.EMAIL_SENT,
    "email.delivered": EventType.EMAIL_DELIVERED,
    "email.bounced": EventType.EMAIL_BOUNCED,
    "email.complained": EventType.EMAIL_COMPLAINT,
    "email.opened": EventType.EMAIL_OPENED,
    "email.clicked": EventType.EMAIL_CLICKED,
    "email.delivery_delayed": EventType.EMAIL_FAILED,
    "email.failed": EventType.EMAIL_FAILED,
}


class ResendProvider(EmailProvider):
    name = "resend"

    def __init__(
        self,
        api_key: str,
        *,
        webhook_secret: str = "",
        cost_per_email: float = DEFAULT_RESEND_COST_PER_EMAIL,
        timeout: float = 15.0,
        _transport=None,
    ) -> None:
        self.api_key = api_key
        self.webhook_secret = webhook_secret
        self.cost_per_email = cost_per_email
        self.timeout = timeout
        # Injectable transport (email -> dict) makes the provider unit-testable
        # without a network. Defaults to the real HTTP call.
        self._transport = _transport or self._http_send

    # ---- sending ----
    def send_email(self, email: OutboundEmail) -> SendResult:
        payload = {
            "from": email.from_email,
            "to": [email.to_email],
            "subject": email.subject,
            "text": email.body,
        }
        if email.reply_to:
            payload["reply_to"] = email.reply_to
        if email.tags:
            # Resend accepts tags as name/value pairs of strings.
            payload["tags"] = [
                {"name": str(k), "value": str(v)} for k, v in email.tags.items()
            ]
        response = self._transport(payload)
        message_id = response.get("id", "")
        if not message_id:
            raise ProviderError(f"resend returned no message id: {response}")
        return SendResult(
            provider_message_id=message_id,
            status="sent",
            timestamp=datetime.now(timezone.utc),
        )

    def _http_send(self, payload: dict) -> dict:
        request = urllib.request.Request(
            _API_URL,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:  # 4xx are permanent; 5xx transient
            detail = exc.read().decode("utf-8", "replace")
            if 400 <= exc.code < 500 and exc.code != 429:
                raise PermanentProviderError(f"resend {exc.code}: {detail}") from exc
            raise ProviderError(f"resend {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ProviderError(f"resend network error: {exc}") from exc

    def get_delivery_status(self, provider_message_id: str) -> str:
        # Resend surfaces status via webhooks; a polling endpoint isn't part of
        # V1. Return "unknown" so callers rely on the event stream.
        return "unknown"

    # ---- webhooks ----
    def parse_webhook(self, headers: dict, body: bytes) -> list[NormalizedEvent]:
        if not self._verify_signature(headers, body):
            raise PermanentProviderError("invalid webhook signature")
        return self._normalize(body)

    def _verify_signature(self, headers: dict, body: bytes) -> bool:
        """Verify a Svix-style signature (Resend's webhook signing).

        Signed content is ``{id}.{timestamp}.{body}`` HMAC-SHA256'd with the
        base64-decoded secret (the part after the ``whsec_`` prefix), base64
        encoded. The header may carry several space-separated ``v1,<sig>`` values.
        """
        if not self.webhook_secret:
            # No secret configured -> refuse to trust the payload.
            return False
        lower = {k.lower(): v for k, v in headers.items()}
        svix_id = lower.get("svix-id")
        svix_ts = lower.get("svix-timestamp")
        svix_sig = lower.get("svix-signature")
        if not (svix_id and svix_ts and svix_sig):
            return False

        secret = self.webhook_secret
        if secret.startswith("whsec_"):
            secret = secret[len("whsec_") :]
        try:
            key = base64.b64decode(secret)
        except Exception:
            key = secret.encode("utf-8")

        signed = f"{svix_id}.{svix_ts}.".encode("utf-8") + body
        expected = base64.b64encode(
            hmac.new(key, signed, hashlib.sha256).digest()
        ).decode("utf-8")

        for part in svix_sig.split():
            _, _, sig = part.partition(",")
            if sig and hmac.compare_digest(sig, expected):
                return True
        return False

    def _normalize(self, body: bytes) -> list[NormalizedEvent]:
        try:
            payload = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise PermanentProviderError(f"malformed webhook body: {exc}") from exc

        rtype = payload.get("type", "")
        event_type = _EVENT_MAP.get(rtype)
        if event_type is None:
            return []  # unknown/unhandled event -> ignore safely

        data = payload.get("data", {}) or {}
        to = data.get("to")
        email = to[0] if isinstance(to, list) and to else (to or "")
        ts = None
        created = payload.get("created_at") or data.get("created_at")
        if created:
            try:
                ts = datetime.fromisoformat(created.replace("Z", "+00:00"))
            except ValueError:
                ts = None
        return [
            NormalizedEvent(
                event_type=event_type,
                provider_message_id=data.get("email_id", ""),
                email=email,
                timestamp=ts,
                metadata={"resend_type": rtype},
            )
        ]

    def validate_configuration(self) -> ConfigStatus:
        if not self.api_key:
            return ConfigStatus(False, "RESEND_API_KEY is not set")
        if not self.webhook_secret:
            return ConfigStatus(
                True, "RESEND_API_KEY set; RESEND_WEBHOOK_SECRET missing (webhooks disabled)"
            )
        return ConfigStatus(True, "resend configured")
