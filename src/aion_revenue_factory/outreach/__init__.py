"""AION Outreach Engine — internal email-campaign orchestration (V1).

A modular, production-minded campaign system built on the existing AION Revenue
Factory conventions (Protocol interfaces + offline references + live adapters).
It pulls qualified leads from Airtable, segments them into campaigns, generates
personalized copy via the existing ``AIGateway``, schedules sends through a
controlled queue, sends through a pluggable ``EmailProvider`` (Resend in V1, SES
later), processes provider webhooks, enforces compliance/suppression, and
reports campaign performance and ROI.

The public surface below is import-light; live provider SDKs are never pulled in
unless actually used.
"""

from .config import OutreachConfig, SendingWindow
from .costs import CampaignCosts
from .eligibility import Eligibility, is_lead_eligible_for_send, valid_email
from .engine import CampaignEngine
from .enums import (
    CampaignState,
    EventType,
    LeadCampaignState,
    QueueStatus,
    SuppressionReason,
)
from .metrics import OutreachDashboard
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
from .personalization import AIPersonalizer, Personalization
from .providers import (
    AmazonSESProvider,
    ConsoleProvider,
    EmailProvider,
    ResendProvider,
    build_provider,
)
from .queue import QueueWorker
from .reply_detection import (
    InboundEmailProvider,
    InboundReply,
    ReplyDetectionService,
)
from .seed import build_pilot_campaign
from .store import InMemoryOutreachStore, OutreachStore
from .suppression import SuppressionService
from .templates import TemplateError, render, required_variables, validate
from .webhooks import WebhookProcessor
from .wiring import (
    OutreachSystem,
    build_outreach_from_env,
    describe_outreach_wiring,
)

__all__ = [
    # config / costs
    "OutreachConfig",
    "SendingWindow",
    "CampaignCosts",
    # enums
    "CampaignState",
    "LeadCampaignState",
    "QueueStatus",
    "EventType",
    "SuppressionReason",
    # models
    "Lead",
    "Campaign",
    "CampaignStep",
    "CampaignLead",
    "EmailMessage",
    "EmailEvent",
    "QueueItem",
    "SuppressionEntry",
    "AIGeneration",
    # services
    "CampaignEngine",
    "QueueWorker",
    "AIPersonalizer",
    "Personalization",
    "SuppressionService",
    "WebhookProcessor",
    "ReplyDetectionService",
    "InboundEmailProvider",
    "InboundReply",
    "OutreachDashboard",
    "Eligibility",
    "is_lead_eligible_for_send",
    "valid_email",
    # templates
    "render",
    "validate",
    "required_variables",
    "TemplateError",
    # store
    "OutreachStore",
    "InMemoryOutreachStore",
    # providers
    "EmailProvider",
    "ConsoleProvider",
    "ResendProvider",
    "AmazonSESProvider",
    "build_provider",
    # seed / wiring
    "build_pilot_campaign",
    "OutreachSystem",
    "build_outreach_from_env",
    "describe_outreach_wiring",
]
