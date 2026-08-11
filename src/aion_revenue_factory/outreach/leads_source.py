"""Lead sources — pull qualified leads into the engine.

Airtable is the CRM/source-of-truth for leads. This module is the dedicated
Airtable read boundary (the spec's ``getLeads()``), plus a deterministic offline
source so the whole pipeline runs with no credentials.

- ``LeadSource`` — the protocol the engine reads through.
- ``SyntheticLeadSource`` — deterministic electrical-contractor leads for
  offline demos/tests.
- ``AirtableLeadSource`` — live Airtable REST reader (stdlib ``urllib``), with
  pagination and a field-mapping you can override to match any base schema.
"""

from __future__ import annotations

import json
import random
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Optional, Protocol, runtime_checkable

from .models import Lead

_API_ROOT = "https://api.airtable.com/v0"


@runtime_checkable
class LeadSource(Protocol):
    def fetch_leads(self, limit: int = 100) -> list[Lead]: ...


# Default mapping from Airtable field names (per the spec's LEADS schema) to Lead.
DEFAULT_FIELD_MAP = {
    "First Name": "first_name",
    "Last Name": "last_name",
    "Company": "company",
    "Job Title": "job_title",
    "Email": "email",
    "Phone": "phone",
    "Website": "website",
    "Industry": "industry",
    "Location": "location",
    "Lead Source": "lead_source",
    "ICP Score": "icp_score",
    "Owner": "owner",
    "Notes": "notes",
}

_BOOL_FIELDS = {
    "Unsubscribed": "unsubscribed",
    "Do Not Contact": "do_not_contact",
}


def lead_from_airtable(record: dict, field_map: dict | None = None) -> Lead:
    """Map one Airtable record ({id, fields}) to a :class:`Lead`."""
    field_map = field_map or DEFAULT_FIELD_MAP
    fields = record.get("fields", {})
    kwargs: dict = {}
    for source, target in field_map.items():
        if source in fields:
            kwargs[target] = fields[source]
    if "icp_score" in kwargs:
        try:
            kwargs["icp_score"] = float(kwargs["icp_score"])
        except (TypeError, ValueError):
            kwargs["icp_score"] = 0.0
    lead = Lead(airtable_id=record.get("id", ""), **{k: v for k, v in kwargs.items() if v is not None})
    for source, target in _BOOL_FIELDS.items():
        if fields.get(source):
            setattr(lead, target, True)
    # Statuses that imply do-not-send.
    if str(fields.get("Bounce Status", "")).lower() in ("bounced", "hard"):
        lead.bounced = True
    if str(fields.get("Reply Status", "")).lower() in ("replied", "yes"):
        lead.has_replied = True
    return lead


class SyntheticLeadSource:
    """Deterministic offline leads (electrical contractors)."""

    _COMPANIES = [
        ("Bright Spark Electric", "Denver, CO"),
        ("Voltify Contractors", "Austin, TX"),
        ("Copperline Electrical", "Phoenix, AZ"),
        ("Northgate Power Systems", "Columbus, OH"),
        ("Summit Wiring Co", "Salt Lake City, UT"),
        ("Ironclad Electric", "Tampa, FL"),
        ("BlueArc Electrical", "Raleigh, NC"),
        ("Cascade Current", "Portland, OR"),
    ]
    _FIRST = ["Mike", "Dana", "Luis", "Priya", "Sam", "Grace", "Tom", "Aisha"]

    def __init__(self, seed: int = 42) -> None:
        self._rng = random.Random(seed)

    def fetch_leads(self, limit: int = 100) -> list[Lead]:
        leads: list[Lead] = []
        for i in range(min(limit, len(self._COMPANIES))):
            company, location = self._COMPANIES[i]
            first = self._FIRST[i % len(self._FIRST)]
            slug = company.lower().replace(" ", "")
            leads.append(
                Lead(
                    first_name=first,
                    last_name="Owner",
                    company=company,
                    job_title="Owner",
                    email=f"{first.lower()}@{slug}.example",
                    industry="Electrical Contracting",
                    location=location,
                    lead_source="synthetic",
                    icp_score=round(self._rng.uniform(60, 95), 1),
                )
            )
        return leads


class AirtableLeadSource:
    """Live Airtable reader for the Leads table (stdlib only)."""

    def __init__(
        self,
        api_key: str,
        base_id: str,
        table: str = "Leads",
        *,
        field_map: Optional[dict] = None,
        timeout: float = 15.0,
        view: str = "",
        max_retries: int = 3,
    ) -> None:
        self.api_key = api_key
        self.base_id = base_id
        self.table = table
        self.field_map = field_map or DEFAULT_FIELD_MAP
        self.timeout = timeout
        self.view = view
        self.max_retries = max_retries

    def _get(self, offset: str = "") -> dict:
        params = {"pageSize": "100"}
        if self.view:
            params["view"] = self.view
        if offset:
            params["offset"] = offset
        url = (
            f"{_API_ROOT}/{self.base_id}/{urllib.parse.quote(self.table)}?"
            + urllib.parse.urlencode(params)
        )
        request = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {self.api_key}"}
        )
        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except (urllib.error.URLError, urllib.error.HTTPError) as exc:  # noqa: PERF203
                last_err = exc
        raise RuntimeError(f"airtable lead fetch failed: {last_err}")

    def fetch_leads(self, limit: int = 100) -> list[Lead]:
        leads: list[Lead] = []
        offset = ""
        while len(leads) < limit:
            page = self._get(offset)
            for record in page.get("records", []):
                leads.append(lead_from_airtable(record, self.field_map))
                if len(leads) >= limit:
                    break
            offset = page.get("offset", "")
            if not offset:
                break
        return leads
