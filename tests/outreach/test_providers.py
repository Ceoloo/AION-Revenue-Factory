import base64
import hashlib
import hmac
import json

import pytest

from aion_revenue_factory.outreach import (
    ConsoleProvider,
    EventType,
    ResendProvider,
    build_provider,
)
from aion_revenue_factory.outreach.providers.base import (
    OutboundEmail,
    PermanentProviderError,
)


def _email(to="dana@voltify.example"):
    return OutboundEmail(to_email=to, subject="hi", body="body", from_email="s@aion.example")


def test_console_provider_records_and_dry_runs():
    provider = ConsoleProvider()
    result = provider.send_email(_email())
    assert result.status == "dry_run"
    assert result.provider_message_id.startswith("dry_")
    assert len(provider.outbox) == 1
    assert provider.validate_configuration().ok


def test_build_provider_dryrun_forces_console():
    from aion_revenue_factory.outreach import OutreachConfig

    cfg = OutreachConfig(dry_run=True, email_provider="resend", resend_api_key="x")
    assert build_provider(cfg).name == "console"


def test_build_provider_resend_when_live():
    from aion_revenue_factory.outreach import OutreachConfig

    cfg = OutreachConfig(dry_run=False, email_provider="resend", resend_api_key="re_x")
    assert build_provider(cfg).name == "resend"


def test_resend_send_via_injected_transport():
    captured = {}

    def transport(payload):
        captured.update(payload)
        return {"id": "resend_123"}

    provider = ResendProvider("re_test", _transport=transport)
    result = provider.send_email(_email())
    assert result.provider_message_id == "resend_123"
    assert result.status == "sent"
    assert captured["to"] == ["dana@voltify.example"]
    assert captured["from"] == "s@aion.example"


def test_resend_no_id_raises():
    provider = ResendProvider("re_test", _transport=lambda p: {})
    with pytest.raises(Exception):
        provider.send_email(_email())


def _svix_headers(secret_b64, msg_id, ts, body: bytes):
    key = base64.b64decode(secret_b64)
    signed = f"{msg_id}.{ts}.".encode() + body
    sig = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
    return {
        "svix-id": msg_id,
        "svix-timestamp": ts,
        "svix-signature": f"v1,{sig}",
    }


def test_resend_webhook_valid_signature_normalizes():
    secret_raw = base64.b64encode(b"supersecretkey").decode()
    provider = ResendProvider("re_x", webhook_secret=f"whsec_{secret_raw}")
    body = json.dumps({
        "type": "email.delivered",
        "data": {"email_id": "resend_123", "to": ["dana@voltify.example"]},
    }).encode()
    headers = _svix_headers(secret_raw, "msg_1", "1700000000", body)
    events = provider.parse_webhook(headers, body)
    assert len(events) == 1
    assert events[0].event_type is EventType.EMAIL_DELIVERED
    assert events[0].provider_message_id == "resend_123"


def test_resend_webhook_bad_signature_rejected():
    secret_raw = base64.b64encode(b"supersecretkey").decode()
    provider = ResendProvider("re_x", webhook_secret=f"whsec_{secret_raw}")
    body = b'{"type":"email.delivered","data":{"email_id":"x"}}'
    headers = {"svix-id": "m", "svix-timestamp": "1", "svix-signature": "v1,deadbeef"}
    with pytest.raises(PermanentProviderError):
        provider.parse_webhook(headers, body)


def test_resend_webhook_no_secret_rejects():
    provider = ResendProvider("re_x", webhook_secret="")
    body = b'{"type":"email.delivered","data":{"email_id":"x"}}'
    with pytest.raises(PermanentProviderError):
        provider.parse_webhook({"svix-id": "m"}, body)


def test_resend_bounce_maps():
    secret_raw = base64.b64encode(b"k").decode()
    provider = ResendProvider("re_x", webhook_secret=f"whsec_{secret_raw}")
    body = json.dumps({"type": "email.bounced", "data": {"email_id": "z", "to": ["a@b.example"]}}).encode()
    headers = _svix_headers(secret_raw, "m", "1", body)
    events = provider.parse_webhook(headers, body)
    assert events[0].event_type is EventType.EMAIL_BOUNCED


def test_ses_provider_is_stub():
    from aion_revenue_factory.outreach import AmazonSESProvider

    provider = AmazonSESProvider()
    assert not provider.validate_configuration().ok
    with pytest.raises(NotImplementedError):
        provider.send_email(_email())
