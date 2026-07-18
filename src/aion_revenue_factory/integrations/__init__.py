"""Pluggable integration points.

Each integration is defined as a small Protocol plus an in-memory reference
implementation. Real deployments swap the in-memory versions for Airtable,
Supabase, an AI gateway, Founder Memory, etc. without touching the departments
or the orchestrator.
"""

from .ai_gateway import AIGateway, TemplateGateway
from .crm import CRM, InMemoryCRM
from .knowledge import KnowledgeBase

__all__ = [
    "AIGateway",
    "TemplateGateway",
    "CRM",
    "InMemoryCRM",
    "KnowledgeBase",
]
