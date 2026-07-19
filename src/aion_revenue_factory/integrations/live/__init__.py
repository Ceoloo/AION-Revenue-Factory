"""Live, production adapters for the factory's integration points.

Each is a drop-in for an offline reference implementation and satisfies the same
protocol. External SDKs (only ``anthropic``) are imported lazily, so importing
this package never pulls in heavy dependencies — you install them only for the
adapters you actually use (``pip install aion-revenue-factory[live]``).
"""

from .airtable_crm import AirtableCRM
from .anthropic_gateway import AnthropicGateway
from .prospect_sources import HttpProspectSource
from .senders import SmtpSender, WebhookSender
from .supabase_crm import SupabaseCRM

__all__ = [
    "AnthropicGateway",
    "AirtableCRM",
    "SupabaseCRM",
    "HttpProspectSource",
    "SmtpSender",
    "WebhookSender",
]
