"""Seed the pilot campaign.

Creates **AION Electrical Contractor Pilot** as a 4-step sequence in DRAFT.
It is never activated or sent automatically — activation is an explicit,
human-confirmed action (see the CLI ``campaigns:start`` / dashboard).

The copy is a deliberate *example*: short, conversational, one problem, one CTA,
no fabricated research, no fake claims. AI personalization adapts it per lead
within these approved bounds.
"""

from __future__ import annotations

from .enums import CampaignState
from .models import Campaign

PILOT_NAME = "AION Electrical Contractor Pilot"


def build_pilot_campaign() -> Campaign:
    campaign = Campaign(
        name=PILOT_NAME,
        description="Pilot outreach to electrical contractors.",
        icp="Electrical contractors, 5-200 employees, commercial focus",
        industry="Electrical Contracting",
        offer="AI Lead Generation + Sales Conversion Audit",
        state=CampaignState.DRAFT,
        daily_send_limit=25,
    )

    # Step 1 — Day 0: initial outreach.
    campaign.add_step(
        delay_days=0,
        subject="quick idea for {{company}}",
        body_template=(
            "Hi {{first_name}},\n\n"
            "I work with electrical contractors on turning more quotes into booked "
            "jobs. Most teams we talk to are strong on the work itself but lose "
            "revenue in slow follow-up.\n\n"
            "Would a short {{offer}} be useful? No cost, just a clear look at where "
            "leads are leaking.\n\n"
            "Worth a 15-minute call?\n\n"
            "{{sender_name}}\n{{sender_company}}"
        ),
        cta="Book a 15-minute call",
    )

    # Step 2 — Day 3: gentle follow-up.
    campaign.add_step(
        delay_days=3,
        subject="re: quick idea for {{company}}",
        body_template=(
            "Hi {{first_name}},\n\n"
            "Circling back — happy to run the {{offer}} for {{company}} and share "
            "two or three specific fixes for converting more of your inbound.\n\n"
            "Want me to put a time on the calendar?\n\n"
            "{{sender_name}}"
        ),
        cta="Grab a time",
    )

    # Step 3 — Day 7: value angle.
    campaign.add_step(
        delay_days=4,  # day 7 = 3 + 4
        subject="converting more electrical quotes",
        body_template=(
            "Hi {{first_name}},\n\n"
            "One pattern we see with contractors: the fastest win is usually "
            "tightening lead response time, not spending more on ads.\n\n"
            "If that's relevant for {{company}}, the audit maps exactly where it "
            "helps. Open to a quick look?\n\n"
            "{{sender_name}}"
        ),
        cta="See the audit",
    )

    # Step 4 — Day 14: final touch.
    campaign.add_step(
        delay_days=7,  # day 14 = 7 + 7
        subject="should I close this out?",
        body_template=(
            "Hi {{first_name}},\n\n"
            "I don't want to crowd your inbox — if now isn't the right time for "
            "{{company}}, no problem at all. I'll leave the {{offer}} open if you "
            "ever want it.\n\n"
            "Just reply and I'll send details.\n\n"
            "{{sender_name}}\n{{sender_company}}"
        ),
        cta="Reply for details",
    )

    return campaign
