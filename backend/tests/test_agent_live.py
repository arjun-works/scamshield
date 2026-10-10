"""Runs the real investigation agent against Gemini. Skipped by default.

From backend/ (PowerShell):
    $env:RUN_LIVE_GEMINI = "1"; uv run pytest tests/test_agent_live.py -s

Uses a handful of free-tier Gemini requests. Data is synthetic and held in memory.
"""

import json
import os

import pytest

from agents.investigation import investigate_case
from agents.policy import valid_section_ids
from app.schemas import TransactionIn, current_step
from app.service import process_transaction
from db.seed_data import seed_store
from db.store import get_store

pytestmark = pytest.mark.skipif(os.getenv("RUN_LIVE_GEMINI") != "1", reason="set RUN_LIVE_GEMINI=1 to call Gemini")


def test_agent_investigates_account_draining_transfer():
    store = get_store()
    store.reset()
    seed_store(store, now_step=current_step())
    customer = store.get_customer("CUST-002")
    record = process_transaction(
        TransactionIn(
            transaction_id="T-LIVE", type="TRANSFER", amount=customer["balance"],
            sender_id="CUST-002", sender_balance_before=customer["balance"], payee_id="C_UNKNOWN_PAYEE",
        ),
        store,
    )

    case = investigate_case(record["case_id"])
    print(json.dumps({"audit_log": case["audit_log"], "investigation": case["investigation"]}, indent=2))

    assert case["investigation_status"] == "complete"
    investigation = case["investigation"]
    assert investigation["probability"] == record["probability"]
    assert {ref["section"] for ref in investigation["policy_references"]} <= valid_section_ids()
    assert set(investigation["tools_called"]) >= {"score_transaction", "get_customer_history", "get_payee_profile"}
    assert case["payment_status"] == "held"  # the agent cannot change it
    store.reset()
