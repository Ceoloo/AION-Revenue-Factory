"""The AI gateway abstraction.

In production this fronts an LLM (via your AI gateway) that writes personalized
copy, audits, and proposals. For a dependency-free, deterministic reference
build we ship a ``TemplateGateway`` that produces coherent text from templates
seeded by the prospect, so the whole pipeline runs offline and reproducibly.

To wire a real model, implement :class:`AIGateway.generate` to call your
gateway and inject it wherever ``TemplateGateway`` is used today.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class AIGateway(Protocol):
    """Anything that can turn a prompt + context into text."""

    def generate(self, prompt: str, context: dict, *, max_words: int = 120) -> str: ...


class TemplateGateway:
    """Deterministic, offline stand-in for a real LLM gateway.

    It fills lightweight templates from the supplied context. The output is
    intentionally plausible sales copy so downstream steps (and humans reading
    the CRM) get realistic-looking artifacts without any API calls.
    """

    def generate(self, prompt: str, context: dict, *, max_words: int = 120) -> str:
        company = context.get("company", "your team")
        industry = context.get("industry", "your market")
        pain = context.get("pain", "manual, repetitive work")
        outcome = context.get("outcome", "measurable revenue lift")
        roi = context.get("roi_multiple")

        kind = prompt.strip().lower()
        if "subject" in kind:
            return f"{company}: cut {pain} with AI"[: max_words * 8]
        if "audit" in kind:
            return (
                f"We reviewed {company} and mapped where {pain} is costing you in "
                f"{industry}. Three fixes drive {outcome}."
            )
        if "proposal" in kind:
            roi_line = f" Projected ROI: {roi}x." if roi else ""
            return (
                f"Proposal for {company}: a phased rollout that removes {pain} and "
                f"delivers {outcome}.{roi_line}"
            )
        # default: an outreach body
        return (
            f"Hi — noticed {company} is scaling in {industry}. Most teams here lose "
            f"time to {pain}. We can deliver {outcome} in weeks, not quarters. "
            f"Worth a 15-minute look?"
        )
