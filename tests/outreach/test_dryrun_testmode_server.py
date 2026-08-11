import json

from aion_revenue_factory.outreach import Lead, OutreachConfig, OutreachSystem
from aion_revenue_factory.outreach.server import route

from .conftest import IN_WINDOW


def _run_one(system, campaign, lead):
    system.engine.create_campaign(campaign)
    system.engine.add_lead(campaign, lead)
    system.engine.activate(campaign)
    system.engine.enqueue_due(campaign, now=IN_WINDOW)
    system.worker.process_once(now=IN_WINDOW)


def test_dry_run_creates_no_real_send_but_records_intent(system, campaign, lead):
    _run_one(system, campaign, lead)
    # console provider = dry-run: intent captured, message id is synthetic
    assert len(system.provider.outbox) == 1
    msg = list(system.store._messages.values())[0]  # noqa: SLF001
    assert msg.provider_message_id.startswith("dry_")


def test_test_mode_redirects_recipient(campaign, lead):
    cfg = OutreachConfig(dry_run=True, email_from="s@aion.example",
                         test_email_address="qa@aion.example", default_timezone="UTC")
    system = OutreachSystem(cfg)
    _run_one(system, campaign, lead)
    email = system.provider.outbox[0]
    assert email.to_email == "qa@aion.example"
    assert email.tags.get("intended_recipient") == lead.email
    msg = list(system.store._messages.values())[0]  # noqa: SLF001
    assert msg.intended_recipient == lead.email


def test_server_health_route(system):
    status, body = route(system, "GET", "/api/health", {}, b"")
    assert status == 200
    assert body["status"] == "ok"


def test_server_dashboard_route(system, campaign, lead):
    _run_one(system, campaign, lead)
    status, body = route(system, "GET", "/api/dashboard", {}, b"")
    assert status == 200
    assert body["emails_sent"] == 1


def test_server_webhook_bad_signature_400(system):
    # console provider parse_webhook returns [] (no events), so use resend path
    from aion_revenue_factory.outreach import ResendProvider

    system.provider = ResendProvider("re_x", webhook_secret="whsec_" )
    system.webhooks.provider = system.provider
    body = b'{"type":"email.delivered","data":{"email_id":"x"}}'
    status, resp = route(system, "POST", "/webhooks/email",
                         {"svix-id": "m", "svix-timestamp": "1", "svix-signature": "v1,bad"}, body)
    assert status == 400


def test_server_unknown_route_404(system):
    status, _ = route(system, "GET", "/nope", {}, b"")
    assert status == 404
