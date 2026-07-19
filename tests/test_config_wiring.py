"""Env-driven wiring: selection logic and an end-to-end live-adapter run."""

import json

from aion_revenue_factory import Dashboard, build_factory_from_env, describe_wiring
from aion_revenue_factory.integrations import InMemoryCRM, TemplateGateway
from aion_revenue_factory.integrations.live import AirtableCRM, AnthropicGateway


def test_describe_wiring_all_offline():
    w = describe_wiring(env={})
    assert w == {
        "gateway": "template (offline)",
        "crm": "in_memory (offline)",
        "prospects": "synthetic (offline)",
        "outreach": "no-op (offline)",
    }


def test_describe_wiring_reports_live_selection():
    env = {
        "ANTHROPIC_API_KEY": "sk-x",
        "AIRTABLE_API_KEY": "k",
        "AIRTABLE_BASE_ID": "b",
        "AION_PROSPECT_URL": "https://api.example.com",
        "AION_OUTREACH_WEBHOOK_URL": "https://esp.example",
    }
    w = describe_wiring(env=env)
    assert w["gateway"] == "anthropic (claude)"
    assert w["crm"] == "airtable"
    assert w["prospects"] == "http_api"
    assert w["outreach"] == "webhook"


def test_build_factory_offline_uses_reference_impls():
    factory = build_factory_from_env(env={})
    assert isinstance(factory.crm, InMemoryCRM) and not hasattr(factory.crm, "_persist")
    assert isinstance(factory.offers.gateway, TemplateGateway)


def test_build_factory_selects_airtable_and_claude(monkeypatch):
    # Avoid constructing a real anthropic client.
    monkeypatch.setattr(AnthropicGateway, "__init__", lambda self, **k: None)
    factory = build_factory_from_env(
        env={
            "ANTHROPIC_API_KEY": "sk-x",
            "AIRTABLE_API_KEY": "k",
            "AIRTABLE_BASE_ID": "b",
        }
    )
    assert isinstance(factory.crm, AirtableCRM)
    assert isinstance(factory.offers.gateway, AnthropicGateway)


def test_end_to_end_run_through_live_adapters(monkeypatch):
    """Drive a full day with Airtable + webhook wired, transports mocked."""
    posts = []

    def fake_airtable(request, timeout=None):
        posts.append(("airtable", request.full_url))

        class R:
            def read(self_inner):
                return b"{}"

            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

        return R()

    sends = []

    monkeypatch.setattr(
        "aion_revenue_factory.integrations.live.airtable_crm.urllib.request.urlopen",
        fake_airtable,
    )

    factory = build_factory_from_env(
        env={"AIRTABLE_API_KEY": "k", "AIRTABLE_BASE_ID": "b"}
    )
    # Swap the outreach transport for a recorder.
    factory.outreach._send = lambda m: sends.append(m) or "sent"

    result = factory.run_day(prospects=20)

    # The workflow produced real revenue and pushed writes to Airtable.
    assert result.discovered == 20
    assert any("Opportunities" in url for _, url in posts)
    assert any("Deals" in url for _, url in posts)
    assert len(sends) == result.contacted
    metrics = Dashboard(factory.crm).metrics()
    assert isinstance(metrics["total_revenue"], float)
