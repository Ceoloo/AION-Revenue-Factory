"""Live CRM backed by Airtable's REST API (stdlib only).

Persists every entity the factory produces to Airtable tables while keeping a
local write-through cache so the dashboard's reads stay fast. Uses the documented
Airtable REST endpoint (``https://api.airtable.com/v0/{baseId}/{table}``) via
``urllib`` — no third-party dependency.

Auth: a personal access token (``AIRTABLE_API_KEY``) with ``data.records:write``
scope on the target base (``AIRTABLE_BASE_ID``).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from .write_through import WriteThroughCRM

_API_ROOT = "https://api.airtable.com/v0"


class AirtableCRM(WriteThroughCRM):
    def __init__(
        self,
        api_key: str,
        base_id: str,
        tables: dict | None = None,
        *,
        timeout: float = 15.0,
        raise_on_error: bool = False,
    ) -> None:
        super().__init__(tables=tables)
        self.api_key = api_key
        self.base_id = base_id
        self.timeout = timeout
        # Off by default: outreach should never crash because a CRM write blipped.
        self.raise_on_error = raise_on_error

    def _persist(self, table: str, record: dict) -> None:
        url = f"{_API_ROOT}/{self.base_id}/{urllib.parse.quote(table)}"
        # Airtable rejects null values; drop them.
        fields = {k: v for k, v in record.items() if v is not None}
        payload = json.dumps({"records": [{"fields": fields}], "typecast": True})
        request = urllib.request.Request(
            url,
            data=payload.encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                resp.read()
        except (urllib.error.URLError, urllib.error.HTTPError):
            if self.raise_on_error:
                raise
            # Otherwise swallow: the local cache still has the record, and a
            # transient CRM outage must not stop the revenue workflow.
