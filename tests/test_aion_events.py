from aion_revenue_factory.integrations.aion_events import (
    KNOWN_EVENTS,
    SOURCE_REPOSITORY,
    SOURCE_SERVICE,
    has_unmasked_sensitive,
    new_event,
    redact_payload,
    validate_event,
)


def test_new_event_is_a_valid_envelope():
    ev = new_event("lead.qualified", payload={"opportunity_id": "o1"}, correlation_id="c1")
    assert validate_event(ev) == []
    d = ev.to_dict()
    assert d["source_service"] == SOURCE_SERVICE
    assert d["source_repository"] == SOURCE_REPOSITORY
    assert d["event_version"] == "1.0"
    assert d["compliance"]["contains_pii"] is False


def test_unknown_event_type_is_rejected():
    ev = new_event("nope.unknown", correlation_id="c1")
    assert any("unknown event_type" in p for p in validate_event(ev))


def test_redaction_masks_sensitive_keys():
    red = redact_payload({"email": "a@b.com", "opportunity_id": "o1"})
    assert red["email"].startswith("masked:")
    assert red["opportunity_id"] == "o1"
    assert not has_unmasked_sensitive(red)


def test_validate_flags_unmasked_pii():
    ev = new_event("lead.qualified", payload={"email": "a@b.com"}, correlation_id="c1")
    assert any("unmasked sensitive" in p for p in validate_event(ev))


def test_known_families_are_registered():
    for et in ("workflow.started", "workflow.completed", "lead.discovered",
               "lead.qualified", "outreach.email_sent", "appointment.booked",
               "billing.payment_succeeded"):
        assert et in KNOWN_EVENTS
