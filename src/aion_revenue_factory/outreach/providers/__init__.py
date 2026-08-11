"""Email provider abstraction + implementations.

``EmailProvider`` is the only seam the campaign engine knows about. Selecting a
provider is configuration (``EMAIL_PROVIDER`` / dry-run), never a code change.
"""

from .base import (
    ConfigStatus,
    EmailProvider,
    NormalizedEvent,
    OutboundEmail,
    PermanentProviderError,
    ProviderError,
    SendResult,
)
from .console import ConsoleProvider
from .resend import ResendProvider
from .ses import AmazonSESProvider


def build_provider(config) -> EmailProvider:
    """Select an ``EmailProvider`` from an ``OutreachConfig``.

    Dry-run always yields the console provider so real credentials may be
    present without any risk of a live send.
    """
    if config.dry_run or config.email_provider == "console":
        return ConsoleProvider()
    if config.email_provider == "resend":
        return ResendProvider(
            config.resend_api_key,
            webhook_secret=config.resend_webhook_secret,
        )
    if config.email_provider == "ses":
        return AmazonSESProvider()
    # Unknown provider name -> fail safe to console rather than send blindly.
    return ConsoleProvider()


__all__ = [
    "EmailProvider",
    "OutboundEmail",
    "SendResult",
    "ConfigStatus",
    "NormalizedEvent",
    "ProviderError",
    "PermanentProviderError",
    "ConsoleProvider",
    "ResendProvider",
    "AmazonSESProvider",
    "build_provider",
]
