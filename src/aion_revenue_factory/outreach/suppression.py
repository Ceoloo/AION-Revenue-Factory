"""Global suppression list.

A single choke point every send passes through. Once an address is here, it is
never contacted again — regardless of campaign, step, or lead record.
"""

from __future__ import annotations

from .enums import SuppressionReason
from .models import SuppressionEntry
from .store import OutreachStore


class SuppressionService:
    def __init__(self, store: OutreachStore) -> None:
        self.store = store

    def is_suppressed(self, email: str) -> bool:
        return self.store.is_suppressed(email)

    def add(self, email: str, reason: SuppressionReason, note: str = "") -> SuppressionEntry:
        """Add (or refresh) an address on the suppression list. Idempotent."""
        entry = SuppressionEntry(email=email, reason=reason, note=note)
        self.store.add_suppression(entry)
        return entry

    def check(self, email: str) -> bool:
        """Alias matching the spec's ``checkSuppression(email)`` naming."""
        return self.is_suppressed(email)
