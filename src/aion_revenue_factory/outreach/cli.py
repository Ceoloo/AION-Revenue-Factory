"""Outreach Engine CLI.

Usage::

    python -m aion_revenue_factory.outreach describe-wiring
    python -m aion_revenue_factory.outreach health
    python -m aion_revenue_factory.outreach seed
    python -m aion_revenue_factory.outreach dry-run --leads 5
    python -m aion_revenue_factory.outreach test-email --to you@example.com

The offline store is process-local, so ``dry-run`` seeds the pilot, enrolls
leads, and runs the full pipeline in one process — the safe way to validate the
system end to end before any real send. With live env vars configured it uses
the real lead source / provider (still governed by ``OUTREACH_DRY_RUN``).
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from .seed import build_pilot_campaign
from .wiring import build_outreach_from_env, describe_outreach_wiring


def _in_window_now(system) -> datetime:
    """A 'now' guaranteed inside the sending window, for a self-contained demo run.

    Real scheduled operation uses the true clock; this keeps the one-shot CLI
    dry-run from silently holding every send when invoked on a weekend/evening.
    """
    now = datetime.now(timezone.utc)
    from .scheduling import within_sending_window, next_send_time

    if within_sending_window(system.config, now):
        return now
    return next_send_time(system.config, now)


def _cmd_describe_wiring(_args) -> int:
    print(json.dumps(describe_outreach_wiring(), indent=2))
    return 0


def _cmd_health(_args) -> int:
    system = build_outreach_from_env()
    print(json.dumps(system.health(), indent=2))
    return 0


def _cmd_seed(_args) -> int:
    campaign = build_pilot_campaign()
    print(f"Seeded campaign (DRAFT, not sent): {campaign.name}")
    print(f"  id: {campaign.id}")
    print(f"  offer: {campaign.offer}")
    print(f"  steps: {len(campaign.steps)}")
    for step in campaign.steps:
        print(f"    step {step.order}: +{step.delay_days}d  subject={step.subject!r}")
    return 0


def _cmd_dry_run(args) -> int:
    system = build_outreach_from_env()
    if not system.config.dry_run and args.force is False:
        print("Refusing to run: OUTREACH_DRY_RUN is not true. Pass --force to send for real.")
        return 2

    engine = system.engine
    campaign = build_pilot_campaign()
    engine.create_campaign(campaign)
    leads = system.lead_source.fetch_leads(args.leads)
    engine.add_leads(campaign, leads)
    engine.activate(campaign)

    now = _in_window_now(system)
    engine.enqueue_due(campaign, now=now)
    result = system.worker.process_once(now=now, limit=args.leads * 4)

    print("=" * 60)
    print("  AION OUTREACH — DRY RUN" if system.config.dry_run else "  AION OUTREACH — LIVE SEND")
    print("=" * 60)
    print(f"campaign: {campaign.name}  ({campaign.id})")
    print(f"leads enrolled: {len(leads)}   worker: {result}")
    print("\nIntended sends:")
    outbox = getattr(system.provider, "outbox", [])
    for email in outbox:
        recipient = email.to_email
        note = ""
        if system.config.test_email_address:
            note = f"  (intended: {email.tags.get('intended_recipient', recipient)})"
        print(f"  → {recipient}{note}\n    subject: {email.subject}")
        if args.verbose:
            print("    body:")
            for line in email.body.splitlines():
                print(f"      {line}")
    print("\nMetrics:")
    print(json.dumps(system.dashboard.campaign_metrics(campaign), indent=2))
    return 0


def _cmd_test_email(args) -> int:
    from .providers.base import OutboundEmail

    system = build_outreach_from_env()
    to = args.to or system.config.test_email_address
    if not to:
        print("No recipient. Pass --to or set TEST_EMAIL_ADDRESS.")
        return 2
    result = system.provider.send_email(
        OutboundEmail(
            to_email=to,
            subject="AION Outreach test email",
            body="This is a test send from the AION Outreach Engine.",
            from_email=system.config.email_from,
            reply_to=system.config.email_reply_to,
        )
    )
    print(json.dumps({
        "provider": getattr(system.provider, "name", ""),
        "to": to,
        "status": result.status,
        "provider_message_id": result.provider_message_id,
        "detail": result.detail,
    }, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="outreach", description="AION Outreach Engine")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("describe-wiring", help="show live vs offline integrations")
    sub.add_parser("health", help="print integration health checks")
    sub.add_parser("seed", help="print the seed pilot campaign (DRAFT)")

    dry = sub.add_parser("dry-run", help="run the full pipeline without sending")
    dry.add_argument("--leads", type=int, default=5)
    dry.add_argument("--verbose", action="store_true", help="print full email bodies")
    dry.add_argument("--force", action="store_true", help="allow real sends if dry-run is off")

    test = sub.add_parser("test-email", help="send a single test email")
    test.add_argument("--to", default="", help="recipient (defaults to TEST_EMAIL_ADDRESS)")

    args = parser.parse_args(argv)
    handlers = {
        "describe-wiring": _cmd_describe_wiring,
        "health": _cmd_health,
        "seed": _cmd_seed,
        "dry-run": _cmd_dry_run,
        "test-email": _cmd_test_email,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
