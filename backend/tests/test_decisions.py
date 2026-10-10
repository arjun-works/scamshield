"""Analyst decisions: what they do to the payment and the feedback they store."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import main
from app.schemas import TransactionIn
from app.service import process_transaction
from db.seed_data import generate_customers
from db.store import get_store
from rules.rules import analyst_decision_blocked

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def customers():
    store = get_store()
    store.reset()
    for customer in generate_customers():
        store.upsert_customer(customer)
    yield
    store.reset()


def held_case() -> dict:
    store = get_store()
    customer = store.get_customer("CUST-001")
    record = process_transaction(
        TransactionIn(
            type="TRANSFER", amount=customer["typical_amount_max"] * 6, sender_id="CUST-001",
            sender_balance_before=customer["balance"], payee_id="C_STRANGER",
        ),
        store,
    )
    return store.get_case(record["case_id"])


def decide(case_id: str, decision: str, reason: str = "Checked with the customer by phone."):
    return client.post(f"/cases/{case_id}/decision", json={"decision": decision, "reason": reason})


@pytest.mark.parametrize("decision, payment_status, is_fraud, false_positive", [
    ("approve", "rejected", True, False),
    ("release", "released", False, False),
    ("reject", "released", False, True),
])
def test_decision_updates_payment_and_writes_feedback(decision, payment_status, is_fraud, false_positive):
    case = held_case()
    response = decide(case["case_id"], decision)
    assert response.status_code == 200

    updated = response.json()["case"]
    assert updated["payment_status"] == payment_status and updated["status"] == "closed"
    assert updated["analyst_decision"]["decision"] == decision
    assert updated["audit_log"][-1]["actor"] == "analyst:analyst-demo"
    assert get_store().get_transaction(case["transaction_id"])["payment_status"] == payment_status

    feedback = client.get("/feedback").json()
    assert len(feedback) == 1
    record = feedback[0]
    assert (record["label_is_fraud"], record["false_positive"]) == (is_fraud, false_positive)
    assert record["transaction_id"] == case["transaction_id"] and record["tier_source"] == "behaviour_rule"
    assert "amount_to_balance_ratio" in record["features"]


def test_a_case_can_only_be_decided_once_and_needs_a_reason():
    case = held_case()
    assert decide(case["case_id"], "release", reason="").status_code == 422
    assert decide(case["case_id"], "sideways").status_code == 422
    assert decide(case["case_id"], "release").status_code == 200
    assert decide(case["case_id"], "approve").status_code == 409
    assert len(client.get("/feedback").json()) == 1
    assert decide("CASE-NOPE", "approve").status_code == 404


def test_payment_cannot_be_sent_during_the_safety_pause_but_can_be_stopped():
    case = held_case()
    now = datetime.now(timezone.utc)
    case.update({"payment_status": "safety_paused", "held_until": (now + timedelta(seconds=60)).isoformat()})

    for decision in ("release", "reject"):
        response = decide(case["case_id"], decision)
        assert response.status_code == 409 and "safety pause" in response.json()["detail"]
    # Once the cooling-off period is over the same decision is allowed.
    assert analyst_decision_blocked("release", case, now=now + timedelta(seconds=61)) is None
    # Stopping the payment is allowed at any time.
    assert decide(case["case_id"], "approve").status_code == 200


def test_feedback_records_scam_signals():
    case = held_case()
    case["scam_signals"] = [{"type": "fake_official", "evidence": "a CBI officer", "confidence": 0.95}]
    decide(case["case_id"], "approve", reason="Digital arrest scam confirmed with the customer.")
    assert client.get("/feedback").json()[0]["scam_signal_types"] == ["fake_official"]
