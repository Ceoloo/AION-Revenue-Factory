"""Live outreach transports (stdlib only).

These satisfy the ``send`` callable the Outreach Workforce uses:
``send(message) -> status_string``.

- ``SmtpSender`` sends EMAIL-channel messages over SMTP (stdlib ``smtplib``).
  Non-email channels fall through to the injected ``fallback`` (default: no-op),
  since SMS / calls / voice go through their own providers.
- ``WebhookSender`` POSTs the message to a URL you control — the seam for an
  ESP, dialer, or voice-AI provider that accepts a JSON webhook.
"""

from __future__ import annotations

import json
import smtplib
import urllib.error
import urllib.request
from email.message import EmailMessage
from typing import Callable

from ...domain import Channel, OutreachMessage


def _noop(_msg: OutreachMessage) -> str:
    return "sent"


class SmtpSender:
    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        from_addr: str,
        *,
        use_tls: bool = True,
        contact_lookup: Callable[[str], str] | None = None,
        fallback: Callable[[OutreachMessage], str] = _noop,
        timeout: float = 20.0,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.from_addr = from_addr
        self.use_tls = use_tls
        # Maps opportunity_id -> recipient email. Required to actually send.
        self.contact_lookup = contact_lookup
        self.fallback = fallback
        self.timeout = timeout

    def __call__(self, message: OutreachMessage) -> str:
        if message.channel is not Channel.EMAIL:
            return self.fallback(message)
        if self.contact_lookup is None:
            return self.fallback(message)
        to_addr = self.contact_lookup(message.opportunity_id)
        if not to_addr:
            return "bounced"

        email = EmailMessage()
        email["From"] = self.from_addr
        email["To"] = to_addr
        email["Subject"] = message.subject
        email.set_content(message.body)

        with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as smtp:
            if self.use_tls:
                smtp.starttls()
            if self.username:
                smtp.login(self.username, self.password)
            smtp.send_message(email)
        return "sent"


class WebhookSender:
    """POST each message to a webhook (ESP / dialer / voice-AI provider)."""

    def __init__(
        self,
        url: str,
        *,
        api_key: str | None = None,
        timeout: float = 15.0,
        raise_on_error: bool = False,
    ) -> None:
        self.url = url
        self.api_key = api_key
        self.timeout = timeout
        self.raise_on_error = raise_on_error

    def __call__(self, message: OutreachMessage) -> str:
        payload = json.dumps(
            {
                "id": message.id,
                "opportunity_id": message.opportunity_id,
                "channel": message.channel.value,
                "subject": message.subject,
                "body": message.body,
            }
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            self.url, data=payload, method="POST", headers=headers
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                resp.read()
            return "sent"
        except (urllib.error.URLError, urllib.error.HTTPError):
            if self.raise_on_error:
                raise
            return "bounced"
