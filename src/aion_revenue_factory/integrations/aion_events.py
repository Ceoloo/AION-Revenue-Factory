"""Slim, vendored AION event contract (v1.0) for the Revenue Factory.

This is a dependency-free port of ``aion_platform.contracts`` that lets this
independent repository emit events conforming to the shared JSON Schema
(``Ceoloo/aion-company-os`` -> ``packages/aion_platform/schema/event_envelope.schema.json``)
without a shared package registry. Keep it in sync with that schema.

Mirrors the port already used by ``techops-local-lead-scraper`` so every AION
repo speaks the identical envelope. See
``aion-company-os/docs/migration/specs/STEP3_REVENUE_OS_EVENT_WIRING.md``.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

EVENT_VERSION = "1.0"
SOURCE_SERVICE = "aion-revenue-factory"
SOURCE_REPOSITORY = "Ceoloo/AION-Revenue-Factory"

# Event families this repo is allowed to emit (subset of the canonical registry).
WORKFLOW_EVENTS = ("workflow.started", "workflow.completed", "workflow.failed")
LEAD_EVENTS = ("lead.discovered", "lead.scored", "lead.qualified", "lead.rejected")
CAMPAIGN_EVENTS = ("campaign.created", "campaign.started", "campaign.completed")
OUTREACH_EVENTS = (
    "outreach.email_queued", "outreach.email_sent",
    "outreach.linkedin_queued", "outreach.linkedin_sent",
)
APPOINTMENT_EVENTS = (
    "appointment.booked", "appointment.qualified",
    "appointment.cancelled", "appointment.no_show",
)
BILLING_EVENTS = (
    "billing.invoice_created", "billing.payment_succeeded", "billing.payment_failed",
)
SERVICE_EVENTS = ("service.health_reported", "production_readiness.scored")
KNOWN_EVENTS = frozenset(
    WORKFLOW_EVENTS + LEAD_EVENTS + CAMPAIGN_EVENTS + OUTREACH_EVENTS
    + APPOINTMENT_EVENTS + BILLING_EVENTS + SERVICE_EVENTS
)

SENSITIVE_KEYS = frozenset(
    {"email", "email_address", "phone", "phone_number", "full_name",
     "first_name", "last_name", "name", "address", "ssn", "national_id"}
)

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def mask_value(value: Any) -> str:
    return "masked:" + hashlib.sha256(str(value).encode()).hexdigest()[:12]


def _is_masked(v: Any) -> bool:
    return v is None or (isinstance(v, str) and v.startswith("masked:"))


def redact_payload(payload: Any, _d: int = 0) -> Any:
    if _d > 12:
        return "…"
    if isinstance(payload, dict):
        return {
            k: (mask_value(v) if isinstance(k, str) and k.lower() in SENSITIVE_KEYS and v is not None
                else redact_payload(v, _d + 1))
            for k, v in payload.items()
        }
    if isinstance(payload, (list, tuple)):
        return [redact_payload(i, _d + 1) for i in payload]
    return payload


def has_unmasked_sensitive(payload: Any, _d: int = 0) -> bool:
    if _d > 12:
        return False
    if isinstance(payload, dict):
        for k, v in payload.items():
            if isinstance(k, str) and k.lower() in SENSITIVE_KEYS and not _is_masked(v):
                return True
            if has_unmasked_sensitive(v, _d + 1):
                return True
    elif isinstance(payload, (list, tuple)):
        return any(has_unmasked_sensitive(i, _d + 1) for i in payload)
    return False


@dataclass
class Event:
    event_type: str
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_version: str = EVENT_VERSION
    source_service: str = SOURCE_SERVICE
    source_repository: str = SOURCE_REPOSITORY
    environment: str = "development"
    occurred_at: str = field(default_factory=_now)
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: Optional[str] = None
    customer_id: Optional[str] = None
    workflow_id: Optional[str] = None
    agent_id: Optional[str] = None
    severity: str = "info"
    payload: dict = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)
    contains_pii: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_version": self.event_version,
            "event_type": self.event_type,
            "source_service": self.source_service,
            "source_repository": self.source_repository,
            "environment": self.environment,
            "occurred_at": self.occurred_at,
            "correlation_id": self.correlation_id,
            "tenant_id": self.tenant_id,
            "customer_id": self.customer_id,
            "workflow_id": self.workflow_id,
            "agent_id": self.agent_id,
            "severity": self.severity,
            "payload": self.payload,
            "metrics": self.metrics,
            "compliance": {
                "contains_pii": self.contains_pii,
                "data_classification": "internal",
                "retention_class": "standard",
            },
        }


def new_event(event_type: str, *, payload=None, metrics=None, correlation_id=None,
              contains_pii=False, environment="development") -> Event:
    return Event(
        event_type=event_type,
        payload=payload or {},
        metrics=metrics or {},
        correlation_id=correlation_id or str(uuid.uuid4()),
        contains_pii=contains_pii,
        environment=environment,
    )


def validate_event(event: "dict | Event") -> list[str]:
    data = event.to_dict() if isinstance(event, Event) else event
    problems: list[str] = []
    for key in ("event_id", "event_version", "event_type", "source_service",
                "source_repository", "environment", "occurred_at", "correlation_id"):
        if not data.get(key):
            problems.append(f"missing required field: {key}")
    et = data.get("event_type")
    if et and et not in KNOWN_EVENTS:
        problems.append(f"unknown event_type for this repo: {et}")
    if data.get("event_id") and not _UUID_RE.match(str(data["event_id"])):
        problems.append("event_id not a uuid")
    comp = data.get("compliance") or {}
    if not comp.get("contains_pii", False) and has_unmasked_sensitive(data.get("payload") or {}):
        problems.append("payload has unmasked sensitive keys but contains_pii is false")
    return problems
