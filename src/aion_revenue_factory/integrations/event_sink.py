"""Event sinks for the Revenue Factory.

The orchestrator emits AION envelope events through an :class:`EventSink`. The
default :class:`NullSink` makes emission a no-op so the offline simulation is
byte-for-byte unchanged. :class:`HttpTelemetrySink` POSTs events to an AION
telemetry endpoint and **never raises into the revenue workflow** (transport
failures are captured, not propagated). :class:`CollectingSink` keeps events in
memory for tests and inspection.
"""

from __future__ import annotations

import json
import urllib.request
from typing import List, Optional, Protocol, Tuple, runtime_checkable

from .aion_events import Event


@runtime_checkable
class EventSink(Protocol):
    """Anything that can receive an emitted :class:`Event`."""

    def emit(self, event: Event) -> None: ...


class NullSink:
    """Discards events. The default — keeps offline runs side-effect free."""

    def emit(self, event: Event) -> None:
        return None


class CollectingSink:
    """Keeps every emitted event in memory (tests / inspection)."""

    def __init__(self) -> None:
        self.events: List[Event] = []

    def emit(self, event: Event) -> None:
        self.events.append(event)

    def types(self) -> List[str]:
        return [e.event_type for e in self.events]


class HttpTelemetrySink:
    """POSTs each event to an AION telemetry URL.

    Telemetry must never break revenue: transport failures are appended to
    ``failures`` (event_id, error) instead of being raised.
    """

    def __init__(self, url: str, api_key: Optional[str] = None, timeout: float = 5.0) -> None:
        self.url = url
        self.api_key = api_key
        self.timeout = timeout
        self.failures: List[Tuple[str, str]] = []

    def emit(self, event: Event) -> None:
        body = json.dumps(event.to_dict()).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(self.url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout):  # nosec B310
                pass
        except Exception as exc:  # noqa: BLE001 - never break the workflow on telemetry
            self.failures.append((event.event_id, str(exc)))
