"""Live prospect discovery from an HTTP enrichment/search API (stdlib only).

``HttpProspectSource`` calls a JSON endpoint you configure (Apollo, Clearbit,
your own enrichment service, a search API…) and maps the returned records into
``Opportunity`` objects. Because vendors differ, the field mapping is injectable:
pass a ``map_record`` callable, or rely on the forgiving default that reads common
field names.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

from ...domain import Contact, Opportunity


def _default_map(record: dict) -> Opportunity:
    """Best-effort mapping from a generic prospect record to an Opportunity."""
    contact = None
    email = record.get("email") or record.get("contact_email")
    if email:
        contact = Contact(
            name=record.get("contact_name") or record.get("name") or "Unknown",
            title=record.get("title") or record.get("contact_title") or "Unknown",
            email=email,
            confidence=float(record.get("contact_confidence", 50.0)),
        )
    return Opportunity(
        name=record.get("company") or record.get("name") or "Unknown",
        industry=record.get("industry") or "Unknown",
        kind=record.get("kind", "business"),
        employees=int(record.get("employees", 10) or 10),
        region=record.get("region", "US"),
        website=record.get("website", ""),
        source=record.get("source", "http_api"),
        signals=record.get("signals") or {},
        contact=contact,
    )


class HttpProspectSource:
    """Fetch prospects from a JSON HTTP endpoint.

    Parameters
    ----------
    url: the endpoint to call.
    api_key / auth_header: optional bearer token sent as ``auth_header``.
    method: ``GET`` (count appended as a query param) or ``POST`` (JSON body).
    results_key: dotted-free top-level key holding the list (default: response is
        itself a list, else ``"results"``/``"data"``/``"records"`` are tried).
    map_record: callable turning one record dict into an Opportunity.
    """

    def __init__(
        self,
        url: str,
        *,
        api_key: str | None = None,
        auth_header: str = "Authorization",
        method: str = "GET",
        results_key: str | None = None,
        map_record: Callable[[dict], Opportunity] = _default_map,
        extra_params: dict | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.url = url
        self.api_key = api_key
        self.auth_header = auth_header
        self.method = method.upper()
        self.results_key = results_key
        self.map_record = map_record
        self.extra_params = extra_params or {}
        self.timeout = timeout

    def _headers(self) -> dict:
        headers = {"Accept": "application/json"}
        if self.api_key:
            value = (
                f"Bearer {self.api_key}"
                if self.auth_header.lower() == "authorization"
                else self.api_key
            )
            headers[self.auth_header] = value
        return headers

    def _extract(self, data) -> list[dict]:
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            if self.results_key:
                return data.get(self.results_key, [])
            for key in ("results", "data", "records", "prospects"):
                if isinstance(data.get(key), list):
                    return data[key]
        return []

    def find(self, count: int) -> list[Opportunity]:
        headers = self._headers()
        if self.method == "POST":
            body = json.dumps({"count": count, **self.extra_params}).encode("utf-8")
            headers["Content-Type"] = "application/json"
            request = urllib.request.Request(
                self.url, data=body, method="POST", headers=headers
            )
        else:
            params = {"count": count, **self.extra_params}
            query = urllib.parse.urlencode(params)
            sep = "&" if "?" in self.url else "?"
            request = urllib.request.Request(
                f"{self.url}{sep}{query}", method="GET", headers=headers
            )

        with urllib.request.urlopen(request, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        records = self._extract(data)[:count]
        return [self.map_record(r) for r in records]
