"""Pluggable integration points.

Each integration is defined as a small Protocol plus an in-memory reference
implementation. Real deployments swap the in-memory versions for Airtable,
Supabase, an AI gateway, Founder Memory, etc. without touching the departments
or the orchestrator.
"""

from .ai_gateway import AIGateway, TemplateGateway
from .aion_events import (
    Event,
    has_unmasked_sensitive,
    new_event,
    redact_payload,
    validate_event,
)
from .crm import CRM, InMemoryCRM
from .event_sink import CollectingSink, EventSink, HttpTelemetrySink, NullSink
from .knowledge import KnowledgeBase

__all__ = [
    "AIGateway",
    "TemplateGateway",
    "CRM",
    "InMemoryCRM",
    "KnowledgeBase",
    "Event",
    "new_event",
    "validate_event",
    "redact_payload",
    "has_unmasked_sensitive",
    "EventSink",
    "NullSink",
    "CollectingSink",
    "HttpTelemetrySink",
]
