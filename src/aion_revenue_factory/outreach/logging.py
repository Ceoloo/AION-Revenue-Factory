"""Structured logging for the Outreach Engine.

Emits one JSON object per event with the standard correlation fields
(``request_id``, ``campaign_id``, ``lead_id``, ``queue_id``, ``provider``,
``event_type``). It never logs secrets, and never logs full email bodies —
callers pass a short ``subject`` at most.
"""

from __future__ import annotations

import json
import logging
import sys
import uuid

_CORRELATION_FIELDS = (
    "request_id",
    "campaign_id",
    "lead_id",
    "queue_id",
    "provider",
    "event_type",
)

# Keys we refuse to emit even if a caller passes them by mistake.
_REDACT = ("api_key", "apikey", "password", "secret", "token", "authorization", "body")

_logger = logging.getLogger("aion.outreach")
if not _logger.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(_handler)
    _logger.setLevel(logging.INFO)


def new_request_id() -> str:
    return f"req_{uuid.uuid4().hex[:12]}"


def set_level(level: str) -> None:
    _logger.setLevel(getattr(logging, level.upper(), logging.INFO))


def _clean(fields: dict) -> dict:
    out = {}
    for key, value in fields.items():
        if any(bad in key.lower() for bad in _REDACT):
            continue
        if value is None or value == "":
            continue
        out[key] = value
    return out


def log_event(event: str, level: str = "info", **fields) -> dict:
    """Log a structured event and return the emitted record (handy for tests)."""
    record = {"event": event}
    record.update(_clean(fields))
    line = json.dumps(record, default=str, sort_keys=True)
    getattr(_logger, level, _logger.info)(line)
    return record
