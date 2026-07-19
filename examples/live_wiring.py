"""Run the factory against whatever live services are configured.

    # offline (no env vars) — same as the default demo
    python examples/live_wiring.py

    # live — set any subset; each service falls back to offline if unset
    export ANTHROPIC_API_KEY=sk-...
    export AIRTABLE_API_KEY=pat...  AIRTABLE_BASE_ID=app...
    python examples/live_wiring.py

Every configured integration is used for real; everything else stays offline,
so you can take the system live one service at a time.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from aion_revenue_factory import Dashboard, build_factory_from_env, describe_wiring  # noqa: E402


def main() -> None:
    print("Integration wiring:")
    print(json.dumps(describe_wiring(), indent=2))

    factory = build_factory_from_env()
    result = factory.run_day(prospects=50)
    metrics = Dashboard(factory.crm).metrics(today_revenue=result.revenue)

    print(
        f"\nRan one day: {result.won} won / {result.proposals} proposals "
        f"from {result.qualified} qualified -> ${result.revenue:,.0f}"
    )
    print(f"MRR: ${metrics['mrr']:,.0f}   Close rate: {metrics['close_rate'] * 100:.1f}%")


if __name__ == "__main__":
    main()
