"""Command-line entry point: run the autonomous loop and print the dashboard.

Usage::

    python -m aion_revenue_factory --days 5 --prospects 50
    python -m aion_revenue_factory --json          # machine-readable output
"""

from __future__ import annotations

import argparse
import json

from .config import build_factory_from_env, describe_wiring
from .dashboard import Dashboard
from .orchestrator import RevenueFactory


def _fmt_money(value: float) -> str:
    return f"${value:,.0f}"


def _print_human(results, metrics, knowledge) -> None:
    print("=" * 60)
    print("  AION REVENUE FACTORY — autonomous run")
    print("=" * 60)
    print(f"{'Day':>4} {'Qual':>5} {'Sent':>5} {'Reply':>6} {'Mtg':>4} "
          f"{'Prop':>5} {'Won':>4} {'Revenue':>12}")
    for r in results:
        print(f"{r.day:>4} {r.qualified:>5} {r.contacted:>5} {r.replied:>6} "
              f"{r.meetings:>4} {r.proposals:>5} {r.won:>4} {_fmt_money(r.revenue):>12}")

    print("\n--- Revenue Dashboard ---")
    rows = [
        ("Total revenue", _fmt_money(metrics["total_revenue"])),
        ("Pipeline value", _fmt_money(metrics["pipeline_value"])),
        ("MRR / ARR", f"{_fmt_money(metrics['mrr'])} / {_fmt_money(metrics['arr'])}"),
        ("Close rate", f"{metrics['close_rate'] * 100:.1f}%"),
        ("Reply rate", f"{metrics['reply_rate'] * 100:.1f}%"),
        ("Proposal win rate", f"{metrics['proposal_win_rate'] * 100:.1f}%"),
        ("Avg deal size", _fmt_money(metrics["avg_deal_size"])),
        ("CAC / LTV", f"{_fmt_money(metrics['cac'])} / {_fmt_money(metrics['ltv'])}"),
        ("LTV:CAC", f"{metrics['ltv_cac_ratio']}x"),
        ("Booked calls", str(metrics["booked_calls"])),
    ]
    for label, value in rows:
        print(f"  {label:<20} {value}")

    print("\n  Revenue by AI agent:")
    for agent, amount in metrics["revenue_by_agent"].items():
        print(f"    {agent:<22} {_fmt_money(amount)}")
    print("\n  Revenue by offer:")
    for offer, amount in metrics["revenue_by_offer"].items():
        print(f"    {offer:<22} {_fmt_money(amount)}")

    print("\n--- Learning Loop (what converted) ---")
    snap = knowledge.snapshot()
    print(f"  wins={snap['wins']}  losses={snap['losses']}")
    print(f"  channel weights: {snap['channel_weight']}")
    print(f"  offer weights:   {snap['offer_weight']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the AION Revenue Factory.")
    parser.add_argument("--days", type=int, default=5, help="business days to run")
    parser.add_argument("--prospects", type=int, default=50, help="prospects per day")
    parser.add_argument("--source-seed", type=int, default=42)
    parser.add_argument("--response-seed", type=int, default=7)
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a report")
    parser.add_argument(
        "--live",
        action="store_true",
        help="wire live integrations from environment variables where configured",
    )
    parser.add_argument(
        "--describe-wiring",
        action="store_true",
        help="print which integrations are live vs offline, then exit",
    )
    args = parser.parse_args(argv)

    if args.describe_wiring:
        print(json.dumps(describe_wiring(), indent=2))
        return 0

    if args.live:
        print(f"Wiring: {json.dumps(describe_wiring())}")
        factory = build_factory_from_env(
            source_seed=args.source_seed, response_seed=args.response_seed
        )
    else:
        factory = RevenueFactory(
            source_seed=args.source_seed, response_seed=args.response_seed
        )
    results = factory.run_days(args.days, prospects=args.prospects)
    today_revenue = results[-1].revenue if results else 0.0
    metrics = Dashboard(factory.crm).metrics(today_revenue=today_revenue)

    if args.json:
        print(json.dumps({
            "days": [vars(r) | {"interactions": len(r.interactions)} for r in results],
            "metrics": metrics,
            "knowledge": factory.knowledge.snapshot(),
        }, indent=2, default=str))
    else:
        _print_human(results, metrics, factory.knowledge)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
