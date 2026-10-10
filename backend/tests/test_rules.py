from datetime import datetime, timedelta, timezone

from rules.rules import SCAM_CONFIDENCE_THRESHOLD, decide, safety_pause, tier_for_score

THRESHOLDS = {"medium": 0.01, "high": 0.71, "critical": 0.94}


def test_tier_boundaries():
    assert tier_for_score(0.0, THRESHOLDS) == "Low"
    assert tier_for_score(0.0099, THRESHOLDS) == "Low"
    assert tier_for_score(0.01, THRESHOLDS) == "Medium"
    assert tier_for_score(0.70, THRESHOLDS) == "Medium"
    assert tier_for_score(0.71, THRESHOLDS) == "High"
    assert tier_for_score(0.94, THRESHOLDS) == "Critical"
    assert tier_for_score(1.0, THRESHOLDS) == "Critical"


def test_tier_action_table():
    low = decide(0.001, THRESHOLDS)
    assert (low.action, low.payment_status, low.create_case) == ("allow", "allowed", False)

    medium = decide(0.3, THRESHOLDS)
    assert (medium.action, medium.payment_status, medium.create_case) == ("verify", "pending_verification", False)

    high = decide(0.8, THRESHOLDS)
    assert (high.action, high.payment_status) == ("hold", "held")
    assert high.create_case and high.start_chat and not high.escalate

    critical = decide(0.99, THRESHOLDS)
    assert (critical.action, critical.payment_status) == ("hold_and_escalate", "held")
    assert critical.create_case and critical.escalate and critical.start_chat


def test_behaviour_rule_raises_large_first_transfer_to_high():
    scam_shape = {"known_customer": True, "is_new_payee": True, "amount_vs_typical_max": 4.0}
    decision = decide(0.001, THRESHOLDS, payment_type="TRANSFER", customer_context=scam_shape)
    assert (decision.tier, decision.action, decision.start_chat) == ("High", "hold", True)
    assert "behaviour rule" in decision.reason

    # Not applied: usual payee, modest amount, unknown customer, other payment type.
    for context, payment_type in [
        ({**scam_shape, "is_new_payee": False}, "TRANSFER"),
        ({**scam_shape, "amount_vs_typical_max": 2.9}, "TRANSFER"),
        ({"known_customer": False}, "TRANSFER"),
        (scam_shape, "PAYMENT"),
    ]:
        assert decide(0.001, THRESHOLDS, payment_type=payment_type, customer_context=context).tier == "Low"

    # It never lowers a tier.
    assert decide(0.99, THRESHOLDS, payment_type="TRANSFER", customer_context=scam_shape).tier == "Critical"


def test_out_of_scope_types_are_low():
    assert decide(0.99, THRESHOLDS, in_model_scope=False).action == "allow"


def test_safety_pause_triggers_on_strong_scam_signal(monkeypatch):
    monkeypatch.setenv("SAFETY_PAUSE_SECONDS", "90")
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    signals = [
        {"type": "digital_arrest", "evidence": "caller said police will arrest me", "confidence": 0.9},
        {"type": "urgency", "evidence": "must pay in 10 minutes", "confidence": 0.4},
    ]
    decision = safety_pause(signals, current_tier="High", now=now)

    assert decision is not None
    assert decision.action == "safety_pause"
    assert decision.payment_status == "safety_paused"
    assert decision.escalate
    assert decision.held_until == (now + timedelta(seconds=90)).isoformat()
    assert "digital_arrest" in decision.reason and "urgency" not in decision.reason


def test_safety_pause_does_not_trigger_on_weak_or_no_signals():
    assert safety_pause([], current_tier="High") is None
    weak = [{"type": "urgency", "evidence": "in a hurry", "confidence": SCAM_CONFIDENCE_THRESHOLD - 0.01}]
    assert safety_pause(weak, current_tier="High") is None


def test_safety_pause_triggers_on_two_moderate_signals_of_different_types():
    moderate = [
        {"type": "urgency_pressure", "evidence": "told to pay within the hour", "confidence": 0.55},
        {"type": "secrecy_demand", "evidence": "told not to mention it", "confidence": 0.5},
    ]
    assert safety_pause(moderate, current_tier="High").action == "safety_pause"
    # The same type twice, or one of them too weak, is not enough.
    assert safety_pause([moderate[0], {**moderate[0], "evidence": "again"}], current_tier="High") is None
    assert safety_pause([moderate[0], {**moderate[1], "confidence": 0.4}], current_tier="High") is None
