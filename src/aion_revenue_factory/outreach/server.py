"""Optional stdlib HTTP surface for the Outreach Engine.

The host project is a library + CLI, so this is a *reference* receiver — not a
new web framework. It uses only ``http.server`` and exposes exactly what needs a
network endpoint: the provider webhook receiver and the health/dashboard reads.
Any real host (FastAPI, Lambda, an existing AION route) can call :func:`route`
the same way.

Routes:
    GET  /api/health            aggregate health
    GET  /api/health/email      email provider config
    GET  /api/health/airtable   airtable config
    GET  /api/health/database   store
    GET  /api/dashboard         metrics overview (no secrets)
    POST /webhooks/email        provider webhook receiver (signature-verified)
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer

from .health import check_airtable, check_email, check_store
from .providers.base import PermanentProviderError
from .wiring import OutreachSystem, build_outreach_from_env


def route(system: OutreachSystem, method: str, path: str, headers: dict, body: bytes) -> tuple[int, dict]:
    """Pure request router. Returns (status_code, json_body)."""
    if method == "GET":
        if path == "/api/health":
            return 200, system.health()
        if path == "/api/health/email":
            return 200, check_email(system.provider)
        if path == "/api/health/airtable":
            return 200, check_airtable(system.config)
        if path == "/api/health/database":
            return 200, check_store(system.store)
        if path == "/api/dashboard":
            return 200, system.dashboard.overview()
        return 404, {"error": "not found"}

    if method == "POST" and path in ("/webhooks/email", "/webhooks/resend"):
        try:
            applied = system.webhooks.handle(headers, body)
        except PermanentProviderError as exc:
            # Bad signature / malformed body -> reject, never mutate state.
            return 400, {"error": str(exc)}
        return 200, {"applied": [e.event_type.value for e in applied], "count": len(applied)}

    return 404, {"error": "not found"}


def make_handler(system: OutreachSystem):
    class _Handler(BaseHTTPRequestHandler):
        def _respond(self, status: int, payload: dict) -> None:
            data = json.dumps(payload, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802
            status, payload = route(system, "GET", self.path, dict(self.headers), b"")
            self._respond(status, payload)

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length) if length else b""
            status, payload = route(system, "POST", self.path, dict(self.headers), body)
            self._respond(status, payload)

        def log_message(self, *_args) -> None:
            # Silence default stderr access logging; the engine logs structured.
            return

    return _Handler


def create_server(system: OutreachSystem, host: str = "127.0.0.1", port: int = 8080) -> HTTPServer:
    return HTTPServer((host, port), make_handler(system))


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - manual run
    import argparse

    parser = argparse.ArgumentParser(description="Run the Outreach HTTP surface")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args(argv)

    system = build_outreach_from_env()
    server = create_server(system, args.host, args.port)
    print(f"Outreach HTTP surface on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
