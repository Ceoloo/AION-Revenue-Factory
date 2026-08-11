"""Environment-driven assembly of the Outreach Engine.

Mirrors the core project's ``build_factory_from_env`` / ``describe_wiring``:
inspect the environment, inject live adapters where credentials exist, fall back
to safe offline references everywhere else. ``OutreachSystem`` is the façade the
CLI and HTTP surface use.
"""

from __future__ import annotations

import os

from ..integrations import AIGateway, TemplateGateway
from .config import OutreachConfig
from .engine import CampaignEngine
from .health import health
from .leads_source import AirtableLeadSource, LeadSource, SyntheticLeadSource
from .logging import set_level
from .metrics import OutreachDashboard
from .personalization import AIPersonalizer
from .providers import EmailProvider, build_provider
from .queue import QueueWorker
from .store import InMemoryOutreachStore, OutreachStore
from .webhooks import WebhookProcessor


def _build_gateway(env: dict) -> AIGateway:
    if env.get("ANTHROPIC_API_KEY") and (env.get("AI_PROVIDER", "").lower() in ("", "anthropic", "claude")):
        try:
            from ..integrations.live import AnthropicGateway

            return AnthropicGateway(
                model=env.get("AION_LLM_MODEL", "claude-opus-4-8"),
                api_key=env["ANTHROPIC_API_KEY"],
            )
        except Exception:
            return TemplateGateway()
    return TemplateGateway()


def _build_lead_source(env: dict) -> LeadSource:
    if env.get("AIRTABLE_API_KEY") and env.get("AIRTABLE_BASE_ID"):
        return AirtableLeadSource(
            env["AIRTABLE_API_KEY"],
            env["AIRTABLE_BASE_ID"],
            table=env.get("AIRTABLE_LEADS_TABLE", "Leads"),
            view=env.get("AIRTABLE_LEADS_VIEW", ""),
        )
    return SyntheticLeadSource()


def _store_kind(env: dict) -> str:
    """Classify DATABASE_URL into 'sqlite' | 'postgres' | 'memory' (no secrets)."""
    url = (env.get("DATABASE_URL") or "").strip()
    if not url:
        return "memory"
    if url.startswith("sqlite:"):
        return "sqlite"
    return "postgres"


def _build_operational_store(env: dict) -> OutreachStore | None:
    """Durable operational store from DATABASE_URL, else in-memory.

    - ``sqlite:///path/to.db`` (or ``sqlite:///:memory:``) -> SqliteOutreachStore
      (durable, stdlib only).
    - any other URL (``postgresql://…``) -> PostgresOutreachStore (needs psycopg).
    - unset -> None (caller falls back to InMemoryOutreachStore).
    """
    kind = _store_kind(env)
    if kind == "memory":
        return None
    url = env["DATABASE_URL"].strip()
    if kind == "sqlite":
        from .stores import SqliteOutreachStore

        # sqlite:///:memory: -> in-memory; sqlite:///rel.db -> "rel.db";
        # sqlite:////abs.db -> "/abs.db" (strip exactly one leading slash).
        raw = url[len("sqlite://"):]
        if raw in ("/:memory:", ":memory:", ""):
            path = ":memory:"
        else:
            path = raw[1:] if raw.startswith("/") else raw
        return SqliteOutreachStore(path)
    from .stores import PostgresOutreachStore

    return PostgresOutreachStore(url)


class OutreachSystem:
    """Everything wired together, ready to drive campaigns."""

    def __init__(
        self,
        config: OutreachConfig,
        *,
        store: OutreachStore | None = None,
        provider: EmailProvider | None = None,
        gateway: AIGateway | None = None,
        lead_source: LeadSource | None = None,
    ) -> None:
        self.config = config
        set_level(config.log_level)
        self.store = store or InMemoryOutreachStore()
        self.gateway = gateway or TemplateGateway()
        self.provider = provider or build_provider(config)
        self.lead_source = lead_source or SyntheticLeadSource()
        self.personalizer = AIPersonalizer(
            self.gateway, self.store, model_name=getattr(self.provider, "name", "template")
        )
        self.engine = CampaignEngine(self.store, config)
        self.worker = QueueWorker(
            self.store, self.provider, self.gateway, config, personalizer=self.personalizer
        )
        self.webhooks = WebhookProcessor(self.store, self.provider)
        self.dashboard = OutreachDashboard(
            self.store, cost_per_email=getattr(self.provider, "cost_per_email", 0.0)
        )

    def health(self, env: dict | None = None) -> dict:
        return health(self.config, self.store, self.provider, env)


def build_outreach_from_env(env: dict | None = None, **overrides) -> OutreachSystem:
    env = os.environ if env is None else env
    config = OutreachConfig.from_env(env)
    overrides.setdefault("store", _build_operational_store(env))
    return OutreachSystem(
        config,
        gateway=_build_gateway(env),
        lead_source=_build_lead_source(env),
        **overrides,
    )


def describe_outreach_wiring(env: dict | None = None) -> dict:
    env = os.environ if env is None else env
    config = OutreachConfig.from_env(env)
    provider = "console (dry-run)" if config.dry_run else config.email_provider
    if env.get("AIRTABLE_API_KEY") and env.get("AIRTABLE_BASE_ID"):
        leads = "airtable"
    else:
        leads = "synthetic (offline)"
    store_kind = {
        "memory": "in_memory (offline, non-durable)",
        "sqlite": "sqlite (durable, stdlib)",
        "postgres": "postgres/supabase (durable)",
    }[_store_kind(env)]
    return {
        "dry_run": config.dry_run,
        "test_mode": bool(config.test_email_address),
        "email_provider": provider,
        "gateway": "anthropic (claude)" if env.get("ANTHROPIC_API_KEY") else "template (offline)",
        "leads": leads,
        "operational_store": store_kind,
        "max_daily_sends": config.max_daily_sends,
        "timezone": config.default_timezone,
        "reply_detection": "PENDING (no InboundEmailProvider wired)",
    }
