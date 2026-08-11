"""Health checks for the Outreach Engine's integrations.

Framework-agnostic: each check returns a small dict the CLI, the optional HTTP
surface, or any AION route can render. Checks never touch secrets beyond asking
a provider/store whether it is configured.
"""

from __future__ import annotations

from .config import OutreachConfig
from .providers.base import EmailProvider
from .store import OutreachStore


def check_store(store: OutreachStore) -> dict:
    try:
        # A trivial read proves the store is answering.
        count = len(list(store.campaigns()))
        return {"component": "database", "status": "ok", "campaigns": count}
    except Exception as exc:  # pragma: no cover - defensive
        return {"component": "database", "status": "error", "detail": str(exc)}


def check_email(provider: EmailProvider) -> dict:
    status = provider.validate_configuration()
    return {
        "component": "email",
        "provider": getattr(provider, "name", "unknown"),
        "status": "ok" if status.ok else "error",
        "detail": status.detail,
    }


def check_airtable(config: OutreachConfig, env: dict | None = None) -> dict:
    import os

    env = os.environ if env is None else env
    configured = bool(env.get("AIRTABLE_API_KEY") and env.get("AIRTABLE_BASE_ID"))
    return {
        "component": "airtable",
        "status": "ok" if configured else "not_configured",
        "detail": "credentials present" if configured else "AIRTABLE_API_KEY/BASE_ID not set (offline)",
    }


def health(config: OutreachConfig, store: OutreachStore, provider: EmailProvider, env: dict | None = None) -> dict:
    checks = [
        check_store(store),
        check_email(provider),
        check_airtable(config, env),
    ]
    ok = all(c["status"] in ("ok", "not_configured") for c in checks)
    return {
        "status": "ok" if ok else "degraded",
        "dry_run": config.dry_run,
        "test_mode": bool(config.test_email_address),
        "checks": checks,
    }
