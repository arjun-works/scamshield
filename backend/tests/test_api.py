import pytest
from fastapi.testclient import TestClient

from app.main import app
from db.store import get_store

client = TestClient(app)


@pytest.fixture(autouse=True)
def empty_store():
    get_store().reset()


def payment(**overrides) -> dict:
    """A small, ordinary transfer; tests override what they need."""
    body = {
        "step": 100, "type": "TRANSFER", "amount": 2_000,
        "sender_id": "C_SENDER", "sender_balance_before": 450_000,
        "payee_id": "C_PAYEE", "payee_balance_before": 0,
    }
    return {**body, **overrides}


def test_score_small_payment_is_allowed():
    result = client.post("/score", json=payment()).json()
    assert result["tier"] == "Low"
    assert result["action"] == "allow"
    assert result["in_model_scope"] is True


def test_score_account_draining_transfer_is_held_with_factors():
    result = client.post("/score", json=payment(amount=450_000)).json()
    assert result["tier"] in ("High", "Critical")
    assert result["payment_status"] == "held"
    assert 0 <= result["probability"] <= 1
    assert len(result["risk_factors"]) == 5
    assert result["risk_factors"][0]["feature"] == "amount_to_balance_ratio"
    assert result["risk_factors"][0]["text"]


def test_score_out_of_scope_type_is_low_by_rule():
    result = client.post("/score", json=payment(type="PAYMENT", amount=450_000)).json()
    assert result["tier"] == "Low"
    assert result["in_model_scope"] is False
    assert result["risk_factors"] == []


def test_score_does_not_save_anything():
    client.post("/score", json=payment(amount=450_000))
    assert client.get("/transactions").json() == []
    assert client.get("/cases").json() == []


def test_score_rejects_bad_input():
    assert client.post("/score", json=payment(amount=-5)).status_code == 422
    assert client.post("/score", json=payment(type="BRIBE")).status_code == 422


def test_held_transaction_creates_case_with_audit_log():
    response = client.post("/transactions", json=payment(amount=450_000, transaction_id="T1")).json()
    case_id = response["case_id"]
    assert case_id and response["transaction"]["payment_status"] == "held"

    case = client.get(f"/cases/{case_id}").json()
    assert case["transaction_id"] == "T1"
    assert case["scam_signals"] == []
    assert [entry["actor"] for entry in case["audit_log"]] == ["risk_model", "rule_engine"]
    assert client.get("/cases", params={"tier": case["tier"]}).json()[0]["case_id"] == case_id


def test_allowed_transaction_creates_no_case():
    response = client.post("/transactions", json=payment()).json()
    assert response["case_id"] is None
    assert len(client.get("/transactions").json()) == 1
    assert client.get("/cases").json() == []


def test_duplicate_transaction_id_is_rejected():
    assert client.post("/transactions", json=payment(transaction_id="T1")).status_code == 200
    assert client.post("/transactions", json=payment(transaction_id="T1")).status_code == 409


def test_payee_history_builds_up_from_stored_transactions():
    client.post("/transactions", json=payment(step=100, sender_id="A", amount=500))
    client.post("/transactions", json=payment(step=100, sender_id="B", amount=700))

    # Same hour: the two payments above are not visible yet.
    same_hour = client.post("/score", json=payment(step=100, sender_id="C")).json()
    assert same_hour["payee_stats"]["payee_distinct_senders_before"] == 0

    next_hour = client.post("/score", json=payment(step=101, sender_id="C")).json()
    assert next_hour["payee_stats"] == {
        "payee_distinct_senders_before": 2,
        "payee_inflow_count_24h": 2,
        "payee_inflow_amount_24h": 1200.0,
    }


def test_held_payments_do_not_count_as_payee_inflows():
    # A held payment never reached the payee, so it is not part of its history.
    held = client.post("/transactions", json=payment(step=100, sender_id="A", amount=450_000)).json()
    assert held["transaction"]["payment_status"] == "held"
    later = client.post("/score", json=payment(step=101, sender_id="B")).json()
    assert later["payee_stats"]["payee_distinct_senders_before"] == 0
    assert later["payee_stats"]["payee_inflow_count_24h"] == 0


def test_transactions_filter_by_sender():
    client.post("/transactions", json=payment(sender_id="A"))
    client.post("/transactions", json=payment(sender_id="B"))
    assert [t["sender_id"] for t in client.get("/transactions", params={"sender_id": "A"}).json()] == ["A"]


def test_unknown_case_is_404():
    assert client.get("/cases/CASE-NOPE").status_code == 404


def test_cors_allows_the_frontend_origin():
    response = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
