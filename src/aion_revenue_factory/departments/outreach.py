"""Department 3 — Outreach Workforce.

AI employees specialized by channel (email, LinkedIn, SMS, cold call, voice AI).
The workforce picks the channel the Learning Engine says converts best for the
prospect, drafts the message via the AI gateway, and "sends" it. Sending is an
injected callable so real deployments swap in an ESP / dialer without changing
the department.
"""

from __future__ import annotations

import random
from datetime import datetime
from typing import Callable

from ..domain import Channel, Offer, Opportunity, OutreachMessage
from ..integrations import AIGateway, KnowledgeBase

# Channel -> the AI employee who owns it.
CHANNEL_AGENTS = {
    Channel.EMAIL: "SDR (Email)",
    Channel.LINKEDIN: "SDR (LinkedIn)",
    Channel.SMS: "SDR (SMS)",
    Channel.COLD_CALL: "SDR (Cold Call)",
    Channel.VOICE_AI: "Voice AI Agent",
}

_ALL_CHANNELS = [c.value for c in Channel]


def _default_send(_msg: OutreachMessage) -> str:
    """Offline no-op transport; returns 'sent'."""
    return "sent"


class OutreachWorkforce:
    def __init__(
        self,
        gateway: AIGateway,
        knowledge: KnowledgeBase,
        send: Callable[[OutreachMessage], str] = _default_send,
        rng: random.Random | None = None,
        epsilon: float = 0.15,
    ) -> None:
        self.gateway = gateway
        self.knowledge = knowledge
        self._send = send
        self._rng = rng or random.Random()
        self.epsilon = epsilon

    def choose_channel(self, opp: Opportunity) -> Channel:
        # Epsilon-greedy over channels: mostly the best-performing channel,
        # sometimes an exploratory one to keep learning which channels work.
        if self._rng.random() < self.epsilon:
            return Channel(self._rng.choice(_ALL_CHANNELS))
        return Channel(self.knowledge.best_channel(_ALL_CHANNELS))

    def compose(self, opp: Opportunity, offer: Offer, channel: Channel) -> OutreachMessage:
        context = {
            "company": opp.name,
            "industry": opp.industry,
            "pain": "manual, repetitive revenue operations",
            "outcome": f"{offer.roi_multiple}x ROI ({offer.headline})",
        }
        subject = self.gateway.generate("subject line", context, max_words=12)
        body = self.gateway.generate("outreach body", context)
        return OutreachMessage(
            opportunity_id=opp.id, channel=channel, subject=subject, body=body
        )

    def send(self, msg: OutreachMessage) -> OutreachMessage:
        msg.status = self._send(msg)
        msg.sent_at = datetime.utcnow()
        return msg

    def agent_for(self, channel: Channel) -> str:
        return CHANNEL_AGENTS[channel]
