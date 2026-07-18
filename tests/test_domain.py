from aion_revenue_factory.domain import Deal, Offer, OfferType, Scores, Stage


def test_deal_progress_is_monotonic():
    deal = Deal(opportunity_id="opp_1")
    deal.advance(Stage.CONTACTED)
    deal.advance(Stage.REPLIED)
    assert deal.reached(Stage.CONTACTED)
    assert deal.reached(Stage.REPLIED)
    assert not deal.reached(Stage.MEETING_BOOKED)


def test_lost_does_not_inflate_funnel_progress():
    """A deal lost at outreach must not count as having replied."""
    deal = Deal(opportunity_id="opp_1")
    deal.advance(Stage.CONTACTED)
    deal.advance(Stage.LOST)
    assert deal.stage is Stage.LOST
    assert deal.reached(Stage.CONTACTED)
    assert not deal.reached(Stage.REPLIED)
    assert not deal.reached(Stage.MEETING_BOOKED)


def test_lost_after_proposal_keeps_earlier_progress():
    deal = Deal(opportunity_id="opp_1")
    for stage in (Stage.CONTACTED, Stage.REPLIED, Stage.MEETING_BOOKED, Stage.PROPOSAL_SENT):
        deal.advance(stage)
    deal.advance(Stage.LOST)
    assert deal.reached(Stage.PROPOSAL_SENT)
    assert deal.stage is Stage.LOST


def test_won_reached_all_milestones():
    deal = Deal(opportunity_id="opp_1")
    deal.advance(Stage.CONTACTED)
    deal.advance(Stage.WON)
    assert deal.stage is Stage.WON
    for milestone in (Stage.CONTACTED, Stage.REPLIED, Stage.MEETING_BOOKED, Stage.PROPOSAL_SENT):
        assert deal.reached(milestone)


def test_scores_composite_and_offer_roi_multiple():
    scores = Scores(revenue_score=80, buying_intent=70, urgency_score=60,
                    contact_confidence=90, estimated_contract_value=50_000)
    assert scores.composite > 0
    offer = Offer(opportunity_id="o", offer_type=OfferType.AUDIT, headline="h",
                  summary="s", price=2_000, roi_estimate=8_000)
    assert offer.roi_multiple == 4.0
