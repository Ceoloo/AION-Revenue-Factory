"""Environment-driven wiring: build a factory from whatever is configured.

``build_factory_from_env()`` inspects environment variables and injects live
adapters where credentials are present, falling back to the offline reference
implementation everywhere else. This lets the exact same code run fully offline
(no env vars) or fully live (all set), or any mix in between.

Recognized variables
--------------------
LLM / copy:
    ANTHROPIC_API_KEY        -> use Claude for outreach/offer copy
    AION_LLM_MODEL           -> model id (default claude-opus-4-8)
CRM (first match wins):
    AIRTABLE_API_KEY + AIRTABLE_BASE_ID   -> Airtable
    SUPABASE_URL + SUPABASE_KEY           -> Supabase
Prospects:
    AION_PROSPECT_URL        -> HTTP prospect source
    AION_PROSPECT_API_KEY    -> its bearer token (optional)
Outreach email:
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM
Outreach webhook:
    AION_OUTREACH_WEBHOOK_URL [+ AION_OUTREACH_WEBHOOK_KEY]
"""

from __future__ import annotations

import os

from .orchestrator import RevenueFactory


def _build_gateway(env: dict):
    if env.get("ANTHROPIC_API_KEY"):
        from .integrations.live import AnthropicGateway

        model = env.get("AION_LLM_MODEL", "claude-opus-4-8")
        return AnthropicGateway(model=model, api_key=env["ANTHROPIC_API_KEY"])
    return None  # -> TemplateGateway


def _build_crm(env: dict):
    if env.get("AIRTABLE_API_KEY") and env.get("AIRTABLE_BASE_ID"):
        from .integrations.live import AirtableCRM

        return AirtableCRM(env["AIRTABLE_API_KEY"], env["AIRTABLE_BASE_ID"])
    if env.get("SUPABASE_URL") and env.get("SUPABASE_KEY"):
        from .integrations.live import SupabaseCRM

        return SupabaseCRM(env["SUPABASE_URL"], env["SUPABASE_KEY"])
    return None  # -> InMemoryCRM


def _build_source(env: dict):
    if env.get("AION_PROSPECT_URL"):
        from .integrations.live import HttpProspectSource

        return HttpProspectSource(
            env["AION_PROSPECT_URL"],
            api_key=env.get("AION_PROSPECT_API_KEY"),
            method=env.get("AION_PROSPECT_METHOD", "GET"),
        )
    return None  # -> SyntheticSource


def _build_sender(env: dict, crm):
    if env.get("AION_OUTREACH_WEBHOOK_URL"):
        from .integrations.live import WebhookSender

        return WebhookSender(
            env["AION_OUTREACH_WEBHOOK_URL"],
            api_key=env.get("AION_OUTREACH_WEBHOOK_KEY"),
        )
    if env.get("SMTP_HOST") and env.get("SMTP_FROM"):
        from .integrations.live import SmtpSender

        def lookup(opp_id: str) -> str:
            opp = crm.get_opportunity(opp_id)
            return opp.contact.email if opp and opp.contact else ""

        return SmtpSender(
            host=env["SMTP_HOST"],
            port=int(env.get("SMTP_PORT", "587")),
            username=env.get("SMTP_USER", ""),
            password=env.get("SMTP_PASSWORD", ""),
            from_addr=env["SMTP_FROM"],
            contact_lookup=lookup,
        )
    return None  # -> offline no-op


def build_factory_from_env(env: dict | None = None, **kwargs) -> RevenueFactory:
    """Construct a RevenueFactory, injecting live adapters where configured."""
    env = os.environ if env is None else env

    crm = _build_crm(env)
    factory = RevenueFactory(
        crm=crm,
        gateway=_build_gateway(env),
        source=_build_source(env),
        **kwargs,
    )
    # The email sender needs to read contacts back out of the CRM the factory
    # actually uses, so wire it after construction.
    sender = _build_sender(env, factory.crm)
    if sender is not None:
        factory.outreach._send = sender
    return factory


def describe_wiring(env: dict | None = None) -> dict:
    """Report which integrations are live vs offline (no secrets included)."""
    env = os.environ if env is None else env
    if env.get("AIRTABLE_API_KEY") and env.get("AIRTABLE_BASE_ID"):
        crm = "airtable"
    elif env.get("SUPABASE_URL") and env.get("SUPABASE_KEY"):
        crm = "supabase"
    else:
        crm = "in_memory (offline)"
    if env.get("AION_OUTREACH_WEBHOOK_URL"):
        outreach = "webhook"
    elif env.get("SMTP_HOST"):
        outreach = "smtp"
    else:
        outreach = "no-op (offline)"
    return {
        "gateway": "anthropic (claude)" if env.get("ANTHROPIC_API_KEY") else "template (offline)",
        "crm": crm,
        "prospects": "http_api" if env.get("AION_PROSPECT_URL") else "synthetic (offline)",
        "outreach": outreach,
    }
