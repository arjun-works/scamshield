"""The investigation agent's tools, tested without calling Gemini."""

import pytest
from fastapi.testclient import TestClient

from agents import tools
from agents.policy import load_sections, search_policy
from agents.schemas import INVESTIGATION_CASE_SCHEMA
from app import main
from app.schemas import TransactionIn, current_step
from app.service import process_transaction
from db.seed_data import seed_store
from db.store import get_store

client = TestClient(main.app)


@pytest.fixture
def held_case() -> dict:
    """A seeded store plus one scam-shaped payment held by the behaviour rule."""
    store = get_store()
    store.reset()
    seed_store(store, now_step=current_step())
    customer = store.get_customer("CUST-001")
    txn = TransactionIn(
        transaction_id="T-SCAM", type="TRANSFER", amount=customer["typical_amount_max"] * 6,
        sender_id="CUST-001", sender_balance_before=customer["balance"], payee_id="C_STRANGER",
    )
    record = process_transaction(txn, store)
    yield store.get_case(record["case_id"])
    store.reset()


def write_case(**overrides) -> dict:
    arguments = {
        "transaction_id": "T-SCAM",
        "top_risk_factors": ["First payment to a new payee at 6x the typical maximum."],
        "historical_evidence": ["All 12 earlier payments went to usual payees."],
        "payee_mule_evidence": ["No earlier payments to this payee are on record."],
        "policy_references": ["POL-3.4", "pol-4.1"],
        "recommended_next_step": "Ask the customer who asked them to make this payment.",
        "investigation_summary": "A large first transfer to an unknown payee.",
    }
    return tools.create_case(**{**arguments, **overrides})


def test_policy_sections_parse_and_search():
    sections = load_sections()
    assert {"POL-1.3", "POL-2.3", "POL-3.4", "POL-4.1", "POL-5.4", "POL-6.4"} <= set(sections)
    assert "1930" in sections["POL-5.4"]["text"]
    assert [s["id"] for s in search_policy("POL-2.3")] == ["POL-2.3"]
    assert any(s["id"].startswith("POL-4") for s in search_policy("mule account indicators"))
    assert search_policy("zzzz") == []


def test_behaviour_rule_holds_the_scam_shaped_payment(held_case):
    assert held_case["tier"] == "High"
    assert held_case["tier_source"] == "behaviour_rule"
    assert held_case["chat_required"] is True
    assert held_case["investigation_status"] == "not_started"
    assert "behaviour rule" in held_case["audit_log"][1]["detail"]


def test_evidence_tools_return_stored_facts(held_case):
    scored = tools.score_transaction("T-SCAM")
    assert scored["tier"] == "High" and scored["tier_source"] == "behaviour_rule"
    assert scored["transaction"]["payee_id"] == "C_STRANGER"

    history = tools.get_customer_history("CUST-001")
    assert history["known_customer"] and history["data_source"] == "synthetic customer profile"
    # The held payment itself is not part of the customer's history.
    assert history["completed_payments_on_record"] == 12 and history["held_or_unverified_payments"] == 1
    assert history["largest_completed_amount"] <= 25_000 and len(history["recent_completed_payments"]) == 10
    assert tools.get_customer_history("C_PAYSIM")["known_customer"] is False

    payee = tools.get_payee_profile("C_STRANGER", "T-SCAM")
    assert payee["distinct_senders_before"] == 0
    assert "The sender has never paid this payee before." in payee["facts"]

    assert tools.find_similar_cases("T-SCAM")["similar_cases"] == []
    assert tools.get_policy("mule account")["sections"]
    assert tools.score_transaction("T-NOPE")["status"] == "error"


def test_create_case_writes_a_grounded_case_file(held_case):
    assert write_case()["status"] == "ok"
    case = get_store().get_case(held_case["case_id"])
    investigation = case["investigation"]

    assert case["investigation_status"] == "complete"
    # Facts are copied from stored data, not taken from the model.
    assert investigation["probability"] == case["probability"]
    assert investigation["transaction"]["amount"] == case["amount"]
    assert [r["section"] for r in investigation["policy_references"]] == ["POL-3.4", "POL-4.1"]
    assert investigation["scam_signals"] == []
    assert case["audit_log"][-1]["actor"] == "investigation_agent"
    assert set(INVESTIGATION_CASE_SCHEMA["required"]) <= set(investigation)


def test_create_case_rejects_invented_policy_and_empty_fields(held_case):
    assert write_case(policy_references=["POL-99.9"])["status"] == "error"
    assert write_case(investigation_summary="")["status"] == "error"
    assert write_case(transaction_id="T-NOPE")["status"] == "error"
    assert get_store().get_case(held_case["case_id"])["investigation"] is None

    # Unknown references are dropped, and the drop is logged for audit.
    assert write_case(policy_references=["POL-4.1", "POL-99.9"])["status"] == "ok"
    assert "POL-99.9" in get_store().get_case(held_case["case_id"])["audit_log"][-1]["detail"]


def test_fallback_model_is_used_and_failed_model_is_skipped_next_time(held_case, monkeypatch):
    from agents import investigation

    attempts = []

    async def fake_run(model_name: str, case: dict) -> None:
        attempts.append(model_name)
        if model_name == "main-model":
            raise RuntimeError("503 UNAVAILABLE")
        write_case()

    monkeypatch.setattr(investigation.config, "GEMINI_MODELS", ["main-model", "fallback-model"])
    monkeypatch.setattr(investigation, "_run_agent", fake_run)
    monkeypatch.setattr(investigation.llm, "_model_failed_at", {})

    case = investigation.investigate_case(held_case["case_id"])
    assert case["investigation_status"] == "complete"
    assert attempts == ["main-model", "fallback-model"]
    assert [e["event"] for e in case["audit_log"][-2:]] == ["investigation_failed", "investigation_written"]

    # A finished case is not investigated again; a forced rerun tries the working model first.
    investigation.investigate_case(held_case["case_id"])
    assert len(attempts) == 2
    investigation.investigate_case(held_case["case_id"], force=True)
    assert attempts[2:] == ["fallback-model"]


def test_investigation_failure_is_recorded_not_raised(held_case, monkeypatch):
    from agents import investigation

    async def always_fails(model_name: str, case: dict) -> None:
        raise RuntimeError("429 RESOURCE_EXHAUSTED")

    monkeypatch.setattr(investigation, "_run_agent", always_fails)
    monkeypatch.setattr(investigation.llm, "_model_failed_at", {})
    case = investigation.investigate_case(held_case["case_id"])
    assert case["investigation_status"] == "failed" and case["investigation"] is None
    assert case["payment_status"] == "held"
    assert "429" in case["audit_log"][-1]["detail"]


def test_investigate_endpoint_runs_once_and_caches(held_case, monkeypatch):
    calls = []

    def fake_investigation(case_id: str, force: bool = False):
        calls.append(case_id)
        write_case()

    monkeypatch.setattr(main, "investigate_case", fake_investigation)
    case_id = held_case["case_id"]

    assert client.post(f"/cases/{case_id}/investigate").status_code == 200
    assert client.get(f"/cases/{case_id}").json()["investigation_status"] == "complete"
    # Second request returns the stored result without running the agent again.
    assert client.post(f"/cases/{case_id}/investigate").json()["investigation"] is not None
    assert calls == [case_id]
    assert client.post("/cases/CASE-NOPE/investigate").status_code == 404
