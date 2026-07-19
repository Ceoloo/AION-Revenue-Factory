"""Live CRM backed by Supabase (PostgREST) via stdlib.

Persists entities to Supabase tables through the PostgREST endpoint
(``{SUPABASE_URL}/rest/v1/{table}``) using ``urllib`` — no third-party
dependency. Like ``AirtableCRM`` it write-throughs to a local cache so reads
stay fast.

Auth: ``SUPABASE_URL`` plus a service-role or anon key (``SUPABASE_KEY``) that
can insert into the target tables. Table names default to lowercase; override via
``tables`` to match your schema.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from .write_through import WriteThroughCRM

# Supabase tables are conventionally lowercase/snake_case.
_LOWER_TABLES = {
    "opportunities": "opportunities",
    "deals": "deals",
    "offers": "offers",
    "messages": "messages",
    "meetings": "meetings",
    "proposals": "proposals",
    "customers": "customers",
    "interactions": "interactions",
}


class SupabaseCRM(WriteThroughCRM):
    def __init__(
        self,
        url: str,
        key: str,
        tables: dict | None = None,
        *,
        timeout: float = 15.0,
        raise_on_error: bool = False,
    ) -> None:
        super().__init__(tables={**_LOWER_TABLES, **(tables or {})})
        self.base_url = url.rstrip("/")
        self.key = key
        self.timeout = timeout
        self.raise_on_error = raise_on_error

    def _persist(self, table: str, record: dict) -> None:
        url = f"{self.base_url}/rest/v1/{table}"
        payload = json.dumps(record).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=payload,
            method="POST",
            headers={
                "apikey": self.key,
                "Authorization": f"Bearer {self.key}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                resp.read()
        except (urllib.error.URLError, urllib.error.HTTPError):
            if self.raise_on_error:
                raise
