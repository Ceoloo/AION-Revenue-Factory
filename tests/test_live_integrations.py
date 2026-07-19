"""Live-adapter tests. All transports are mocked — no real network calls."""

import io
import json

import pytest

from aion_revenue_factory.domain import Channel, Contact, Deal, Opportunity, OutreachMessage, Stage
from aion_revenue_factory.integrations.live import (
    AirtableCRM,
    AnthropicGateway,
    HttpProspectSource,
    SmtpSender,
    SupabaseCRM,
    WebhookSender,
)
from aion_revenue_factory.scoring import score_opportunity


class _FakeResp:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


# --- AI gateway ---------------------------------------------------------


class _FakeBlock:
    type = "text"

    def __init__(self, text):
        self.text = text


class _FakeMessage:
    def __init__(self, text):
        self.content = [_FakeBlock(text)]


class _FakeMessages:
    def __init__(self, text):
        self._text = text
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeMessage(self._text)


class _FakeClient:
    def __init__(self, text):
        self.messages = _FakeMessages(text)


def test_anthropic_gateway_uses_injected_client():
    client = _FakeClient("Cut manual ops with AI.")
    gw = AnthropicGateway(client=client)
    out = gw.generate("outreach body", {"company": "Acme"}, max_words=40)
    assert out == "Cut manual ops with AI."
    assert client.messages.calls[0]["model"] == "claude-opus-4-8"
    # context is serialized into the user message
    assert "Acme" in client.messages.calls[0]["messages"][0]["content"]


# --- Airtable / Supabase CRM (write-through) ----------------------------


def _opp():
    o = Opportunity(
        name="Acme", industry="SaaS", employees=40,
        contact=Contact("Sam", "CEO", "sam@acme.com", 80.0),
        signals={"hiring": True},
    )
    o.scores = score_opportunity(o)
    return o


def test_airtable_crm_posts_and_caches(monkeypatch):
    captured = []

    def fake_urlopen(request, timeout=None):
        captured.append((request.full_url, json.loads(request.data.decode())))
        return _FakeResp(b'{"records":[{"id":"rec1"}]}')

    monkeypatch.setattr(
        "aion_revenue_factory.integrations.live.airtable_crm.urllib.request.urlopen",
        fake_urlopen,
    )
    crm = AirtableCRM("key", "base123", raise_on_error=True)
    opp = _opp()
    crm.upsert_opportunity(opp)

    # It POSTed to the right base/table with the record fields...
    url, body = captured[0]
    assert "base123/Opportunities" in url
    assert body["records"][0]["fields"]["name"] == "Acme"
    # ...and the local cache still serves reads for the dashboard.
    assert crm.get_opportunity(opp.id) is opp


def test_airtable_crm_swallows_transport_errors(monkeypatch):
    import urllib.error

    def boom(*a, **k):
        raise urllib.error.URLError("down")

    monkeypatch.setattr(
        "aion_revenue_factory.integrations.live.airtable_crm.urllib.request.urlopen",
        boom,
    )
    crm = AirtableCRM("key", "base123")  # raise_on_error defaults False
    deal = Deal(opportunity_id="opp_1", amount=1000)
    deal.advance(Stage.WON)
    crm.upsert_deal(deal)  # must not raise
    assert list(crm.deals())[0].id == deal.id


def test_supabase_crm_posts_row(monkeypatch):
    captured = []

    def fake_urlopen(request, timeout=None):
        captured.append((request.full_url, json.loads(request.data.decode()), dict(request.headers)))
        return _FakeResp(b"")

    monkeypatch.setattr(
        "aion_revenue_factory.integrations.live.supabase_crm.urllib.request.urlopen",
        fake_urlopen,
    )
    crm = SupabaseCRM("https://x.supabase.co", "servicekey", raise_on_error=True)
    crm.upsert_opportunity(_opp())
    url, row, headers = captured[0]
    assert url == "https://x.supabase.co/rest/v1/opportunities"
    assert row["name"] == "Acme"
    assert headers["Apikey"] == "servicekey"


# --- HTTP prospect source ----------------------------------------------


def test_http_prospect_source_maps_records(monkeypatch):
    payload = {
        "results": [
            {"company": "Beta Co", "industry": "Fintech", "employees": 50,
             "email": "cto@beta.co", "title": "CTO", "signals": {"recent_funding": True}},
            {"company": "Gamma", "industry": "Retail", "employees": 12},
        ]
    }

    def fake_urlopen(request, timeout=None):
        assert "count=5" in request.full_url
        return _FakeResp(json.dumps(payload).encode())

    monkeypatch.setattr(
        "aion_revenue_factory.integrations.live.prospect_sources.urllib.request.urlopen",
        fake_urlopen,
    )
    source = HttpProspectSource("https://api.example.com/search", api_key="tok")
    opps = source.find(5)
    assert [o.name for o in opps] == ["Beta Co", "Gamma"]
    assert opps[0].contact and opps[0].contact.email == "cto@beta.co"
    assert opps[1].contact is None


# --- Senders ------------------------------------------------------------


def test_webhook_sender_posts(monkeypatch):
    captured = []

    def fake_urlopen(request, timeout=None):
        captured.append(json.loads(request.data.decode()))
        return _FakeResp(b"ok")

    monkeypatch.setattr(
        "aion_revenue_factory.integrations.live.senders.urllib.request.urlopen",
        fake_urlopen,
    )
    sender = WebhookSender("https://esp.example/send", api_key="k", raise_on_error=True)
    msg = OutreachMessage(opportunity_id="opp_1", channel=Channel.EMAIL, subject="Hi", body="Body")
    assert sender(msg) == "sent"
    assert captured[0]["subject"] == "Hi"


def test_webhook_sender_reports_bounce_on_error(monkeypatch):
    import urllib.error

    def boom(*a, **k):
        raise urllib.error.URLError("nope")

    monkeypatch.setattr(
        "aion_revenue_factory.integrations.live.senders.urllib.request.urlopen",
        boom,
    )
    sender = WebhookSender("https://esp.example/send")
    msg = OutreachMessage(opportunity_id="opp_1", channel=Channel.SMS, subject="s", body="b")
    assert sender(msg) == "bounced"


def test_smtp_sender_sends_email(monkeypatch):
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            sent["host"] = host

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            sent["tls"] = True

        def login(self, u, p):
            sent["login"] = u

        def send_message(self, email):
            sent["to"] = email["To"]
            sent["subject"] = email["Subject"]

    monkeypatch.setattr(
        "aion_revenue_factory.integrations.live.senders.smtplib.SMTP", FakeSMTP
    )
    sender = SmtpSender(
        host="smtp.example", port=587, username="u", password="p",
        from_addr="rev@aion.example",
        contact_lookup=lambda opp_id: "buyer@acme.com",
    )
    msg = OutreachMessage(opportunity_id="opp_1", channel=Channel.EMAIL, subject="Hi", body="Body")
    assert sender(msg) == "sent"
    assert sent["to"] == "buyer@acme.com"
    assert sent["tls"] is True


def test_smtp_sender_falls_back_for_non_email():
    calls = []
    sender = SmtpSender(
        host="h", port=1, username="", password="", from_addr="a@b.c",
        fallback=lambda m: calls.append(m) or "sent",
    )
    msg = OutreachMessage(opportunity_id="opp_1", channel=Channel.LINKEDIN, subject="s", body="b")
    assert sender(msg) == "sent"
    assert len(calls) == 1
