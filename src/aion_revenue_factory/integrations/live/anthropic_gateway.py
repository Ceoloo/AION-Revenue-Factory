"""Live AI gateway backed by Claude (the official ``anthropic`` SDK).

This is the production drop-in for ``TemplateGateway``: it satisfies the same
``AIGateway`` protocol but generates real, personalized copy with Claude. The
SDK is imported lazily so the core package stays dependency-free — you only need
``anthropic`` installed when you actually use this class (``pip install
aion-revenue-factory[live]``).

Credentials resolve the standard way: ``ANTHROPIC_API_KEY``, or an
``ant auth login`` profile. See https://docs.claude.com for setup.
"""

from __future__ import annotations

import json

# Default model. Opus 4.8 is the most capable; set AION_LLM_MODEL to a cheaper
# tier (e.g. claude-haiku-4-5) for high-volume, cost-sensitive copy generation.
DEFAULT_MODEL = "claude-opus-4-8"

_SYSTEM = (
    "You are an expert B2B revenue copywriter working inside the AION Revenue "
    "Factory. You write sharp, specific, personalized sales copy grounded in the "
    "prospect's context. No fluff, no cliches, no emoji. Return only the copy "
    "requested — no preamble, no quotation marks, no commentary."
)


class AnthropicGateway:
    """AIGateway implementation that calls Claude via the official SDK."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
        client=None,
    ) -> None:
        self.model = model
        if client is not None:
            self._client = client
        else:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover - env dependent
                raise ImportError(
                    "AnthropicGateway requires the 'anthropic' package. "
                    "Install it with: pip install aion-revenue-factory[live]"
                ) from exc
            # A bare client resolves ANTHROPIC_API_KEY or an ant-auth profile.
            self._client = (
                anthropic.Anthropic(api_key=api_key)
                if api_key
                else anthropic.Anthropic()
            )

    def generate(self, prompt: str, context: dict, *, max_words: int = 120) -> str:
        user = (
            f"Task: {prompt}\n"
            f"Prospect context (JSON): {json.dumps(context, default=str)}\n"
            f"Write at most {max_words} words."
        )
        # Short marketing copy — a small, non-streaming completion is plenty.
        response = self._client.messages.create(
            model=self.model,
            max_tokens=min(1024, max_words * 8 + 64),
            system=_SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(
            block.text for block in response.content if block.type == "text"
        ).strip()
        return text
