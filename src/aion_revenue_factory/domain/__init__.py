"""Core domain models for the AION Revenue Factory.

These dataclasses are the shared vocabulary that every department, AI employee,
and integration speaks. Keeping them dependency-free (stdlib only) means the
domain can be reused by the orchestrator, the dashboard, and any external
integration (Airtable, Supabase, an AI gateway) without coupling.
"""

from .enums import Channel, OfferType, Stage
from .models import (
    Contact,
    Customer,
    Deal,
    Interaction,
    Meeting,
    Offer,
    Opportunity,
    OutreachMessage,
    Proposal,
    Scores,
)

__all__ = [
    "Channel",
    "OfferType",
    "Stage",
    "Contact",
    "Customer",
    "Deal",
    "Interaction",
    "Meeting",
    "Offer",
    "Opportunity",
    "OutreachMessage",
    "Proposal",
    "Scores",
]
