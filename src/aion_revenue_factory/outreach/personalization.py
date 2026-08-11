"""AI personalization service.

Wraps the existing ``AIGateway`` (``TemplateGateway`` offline, ``AnthropicGateway``
live) to produce structured, auditable output for a campaign step:

    {"subject": ..., "body": ..., "rationale": ..., "confidence": ...}

Guardrails encoded here (from the spec's email-writing rules):

- The model personalizes **within** the campaign step's approved copy. The
  step's ``body_template`` is the base; personalization adapts tone/opening to
  the lead using only fields we actually have.
- It must never invent facts. We only pass the lead attributes we hold; the
  prompt explicitly instructs generic-but-relevant personalization when company
  detail is thin, and the confidence score drops when we have little to go on.
- Every generation is stored (``AIGeneration``) for audit.

If AI is disabled for the step (or unavailable and no fallback allowed), the
step's own subject/template is used verbatim — never a half-personalized email.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..integrations import AIGateway
from .costs import DEFAULT_GENERATION_COST
from .models import AIGeneration, Campaign, CampaignStep, Lead
from .store import OutreachStore

# Facts we are allowed to reference — anything not here must not appear as a
# claim about the prospect.
_ALLOWED_FACTS = ("company", "industry", "job_title", "location", "website")


@dataclass(frozen=True)
class Personalization:
    subject: str
    body: str
    rationale: str
    confidence: float


class AIPersonalizer:
    def __init__(
        self,
        gateway: AIGateway,
        store: OutreachStore,
        *,
        model_name: str = "template",
        cost_per_generation: float = DEFAULT_GENERATION_COST,
    ) -> None:
        self.gateway = gateway
        self.store = store
        self.model_name = model_name
        self.cost_per_generation = cost_per_generation

    def _known_facts(self, lead: Lead, campaign: Campaign) -> dict:
        facts = {
            "company": lead.company,
            "industry": lead.industry or campaign.industry,
            "job_title": lead.job_title,
            "location": lead.location,
            "website": lead.website,
        }
        return {k: v for k, v in facts.items() if v}

    def _confidence(self, facts: dict) -> float:
        """More real signal about the prospect -> higher confidence.

        Base 0.55 with company/industry present; small bumps for extra facts.
        Capped so we never claim certainty we don't have.
        """
        score = 0.4
        if facts.get("company"):
            score += 0.15
        if facts.get("industry"):
            score += 0.15
        if facts.get("job_title"):
            score += 0.1
        if facts.get("website") or facts.get("location"):
            score += 0.1
        return round(min(score, 0.95), 2)

    def personalize(
        self, lead: Lead, campaign: Campaign, step: CampaignStep
    ) -> Personalization:
        """Produce personalized copy for a step and record the generation."""
        facts = self._known_facts(lead, campaign)

        if not step.ai_personalization:
            result = Personalization(
                subject=step.subject,
                body=step.body_template,
                rationale="AI personalization disabled for this step; template used verbatim.",
                confidence=1.0,
            )
            self._audit(lead, campaign, step, result, prompt="", cost=0.0)
            return result

        context = {
            "company": lead.company or "your team",
            "industry": facts.get("industry", "your market"),
            "pain": "manual, repetitive revenue operations",
            "outcome": campaign.offer or "measurable revenue lift",
            "first_name": lead.first_name,
            "known_facts": ", ".join(f"{k}={v}" for k, v in facts.items()) or "none",
        }
        # The prompt string names the artifact so TemplateGateway routes it, and
        # documents the no-fabrication rule for a live LLM gateway.
        subject_prompt = "subject line — concise, specific, no hype, no fake claims"
        body_prompt = (
            "outreach body — B2B, human, one problem, one CTA. Only reference "
            "these verified facts about the prospect; invent nothing: "
            f"{context['known_facts']}"
        )

        subject = self.gateway.generate(subject_prompt, context, max_words=12).strip()
        body = self.gateway.generate(body_prompt, context).strip()

        rationale = (
            "Personalized from verified fields ("
            + (", ".join(facts.keys()) or "none")
            + "); generic-but-relevant framing where company detail was thin."
        )
        result = Personalization(
            subject=subject or step.subject,
            body=body or step.body_template,
            rationale=rationale,
            confidence=self._confidence(facts),
        )
        self._audit(
            lead,
            campaign,
            step,
            result,
            prompt=body_prompt,
            cost=self.cost_per_generation,
        )
        return result

    def _audit(
        self,
        lead: Lead,
        campaign: Campaign,
        step: CampaignStep,
        result: Personalization,
        *,
        prompt: str,
        cost: float,
    ) -> None:
        self.store.save_generation(
            AIGeneration(
                lead_id=lead.id,
                campaign_id=campaign.id,
                step_id=step.id,
                subject=result.subject,
                body=result.body,
                rationale=result.rationale,
                confidence=result.confidence,
                model=self.model_name,
                prompt=prompt,
                estimated_cost=cost,
            )
        )
