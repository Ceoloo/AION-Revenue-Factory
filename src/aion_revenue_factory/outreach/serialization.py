"""Lossless (de)serialization of outreach models to/from JSON-safe dicts.

The SQL stores persist each entity as a compact set of indexed columns plus a
full JSON ``data`` blob, so a row round-trips back to the exact dataclass with
no field-by-field column mapping to drift out of sync. Enums serialize to their
string value; datetimes to ISO-8601; everything else is already primitive.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from enum import Enum
from typing import Optional

from .enums import (
    CampaignState,
    EventType,
    LeadCampaignState,
    QueueStatus,
    SuppressionReason,
)
from .models import (
    AIGeneration,
    Campaign,
    CampaignLead,
    CampaignStep,
    EmailEvent,
    EmailMessage,
    Lead,
    QueueItem,
    SuppressionEntry,
)


def _default(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"cannot serialize {type(value)!r}")


def to_dict(obj) -> dict:
    """Return a fully JSON-primitive dict for a dataclass instance."""
    return json.loads(json.dumps(asdict(obj), default=_default))


def to_json(obj) -> str:
    return json.dumps(asdict(obj), default=_default, sort_keys=True)


def _dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    return datetime.fromisoformat(value)


# ---- from_dict rebuilders (explicit: enum/datetime fields are known) ----

def lead_from_dict(d: dict) -> Lead:
    return Lead(**d)


def step_from_dict(d: dict) -> CampaignStep:
    return CampaignStep(**d)


def campaign_from_dict(d: dict) -> Campaign:
    d = dict(d)
    steps = [step_from_dict(s) for s in d.pop("steps", [])]
    d["state"] = CampaignState(d["state"])
    d["created_at"] = _dt(d.get("created_at")) or datetime.utcnow()
    return Campaign(steps=steps, **d)


def campaign_lead_from_dict(d: dict) -> CampaignLead:
    d = dict(d)
    d["state"] = LeadCampaignState(d["state"])
    d["last_sent_at"] = _dt(d.get("last_sent_at"))
    d["next_step_at"] = _dt(d.get("next_step_at"))
    return CampaignLead(**d)


def queue_item_from_dict(d: dict) -> QueueItem:
    d = dict(d)
    d["status"] = QueueStatus(d["status"])
    d["scheduled_at"] = _dt(d.get("scheduled_at"))
    d["last_attempt_at"] = _dt(d.get("last_attempt_at"))
    d["created_at"] = _dt(d.get("created_at")) or datetime.utcnow()
    d["completed_at"] = _dt(d.get("completed_at"))
    return QueueItem(**d)


def message_from_dict(d: dict) -> EmailMessage:
    d = dict(d)
    d["created_at"] = _dt(d.get("created_at")) or datetime.utcnow()
    d["sent_at"] = _dt(d.get("sent_at"))
    return EmailMessage(**d)


def event_from_dict(d: dict) -> EmailEvent:
    d = dict(d)
    d["event_type"] = EventType(d["event_type"])
    d["timestamp"] = _dt(d.get("timestamp")) or datetime.utcnow()
    return EmailEvent(**d)


def suppression_from_dict(d: dict) -> SuppressionEntry:
    d = dict(d)
    d["reason"] = SuppressionReason(d["reason"])
    d["created_at"] = _dt(d.get("created_at")) or datetime.utcnow()
    return SuppressionEntry(**d)


def generation_from_dict(d: dict) -> AIGeneration:
    d = dict(d)
    d["created_at"] = _dt(d.get("created_at")) or datetime.utcnow()
    return AIGeneration(**d)
