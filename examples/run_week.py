"""Run the factory for a week and print a compact report.

    python examples/run_week.py

Demonstrates the full loop end-to-end: discovery -> offers -> outreach ->
meetings -> proposals -> closes -> onboarding -> learning, with the dashboard
and the learned weights at the end.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the package importable when run straight from a checkout.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from aion_revenue_factory import Dashboard, RevenueFactory  # noqa: E402


def main() -> None:
    factory = RevenueFactory()
    results = factory.run_days(7, prospects=50)

    print("Day-by-day:")
    for r in results:
        print(
            f"  Day {r.day}: {r.won} won / {r.proposals} proposals / "
            f"{r.meetings} meetings from {r.qualified} qualified "
            f"-> ${r.revenue:,.0f}"
        )

    metrics = Dashboard(factory.crm).metrics(today_revenue=results[-1].revenue)
    print("\nWeek totals:")
    print(f"  Revenue:        ${metrics['total_revenue']:,.0f}")
    print(f"  MRR / ARR:      ${metrics['mrr']:,.0f} / ${metrics['arr']:,.0f}")
    print(f"  Close rate:     {metrics['close_rate'] * 100:.1f}%")
    print(f"  Proposal win %: {metrics['proposal_win_rate'] * 100:.1f}%")
    print(f"  Booked calls:   {metrics['booked_calls']}")

    print("\nWhat the factory learned converts best:")
    snap = factory.knowledge.snapshot()
    top_channel = max(snap["channel_weight"], key=snap["channel_weight"].get)
    top_offer = max(snap["offer_weight"], key=snap["offer_weight"].get)
    print(f"  Best channel: {top_channel}")
    print(f"  Best offer:   {top_offer}")


if __name__ == "__main__":
    main()
