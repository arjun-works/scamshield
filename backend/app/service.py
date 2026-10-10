"""Processes a payment end to end: score, rules, customer context, save, case.

Used by the API and by the seed script, so both produce identical records.
"""

from app.schemas import TransactionIn
from app.scoring import PAYEE_STAT_FIELDS, resolve_payee_stats, score_transaction
from db.store import now_iso
from rules.rules import ANALYST_DECISIONS, analyst_decision_blocked


def build_customer_context(txn: TransactionIn, store) -> dict:
    """What the (synthetic) customer profile says about this payment.

    PaySim has no customer history, so demo customers get a synthetic profile.
    This context is evidence for the investigation agent and the analyst. It
    is not a model input and does not change the tier.
    """
    customer = store.get_customer(txn.sender_id)
    if customer is None:
        return {"known_customer": False}

    usual = {p["payee_id"]: p for p in customer["usual_payees"]}
    paid_before = store.has_paid_before(txn.sender_id, txn.payee_id, txn.step)
    is_new_payee = txn.payee_id not in usual and not paid_before
    typical_max = customer["typical_amount_max"]
    ratio = round(txn.amount / typical_max, 2)

    notes = []
    if is_new_payee:
        notes.append("This is the customer's first payment to this payee.")
    else:
        notes.append("The customer has paid this payee before or lists it as a usual payee.")
    if txn.amount > typical_max:
        notes.append(f"The amount is {ratio}x the customer's typical maximum of {typical_max:,.0f}.")
    else:
        notes.append("The amount is within the customer's typical range.")

    return {
        "known_customer": True,
        "source": "synthetic customer profile",
        "customer_name": customer["name"],
        "preferred_language": customer["preferred_language"],
        "segment": customer["segment"],
        "payee_name": usual.get(txn.payee_id, {}).get("name"),
        "is_new_payee": is_new_payee,
        "typical_amount_min": customer["typical_amount_min"],
        "typical_amount_max": typical_max,
        "amount_vs_typical_max": ratio,
        "above_typical_amount": txn.amount > typical_max,
        "notes": notes,
    }


def process_transaction(txn: TransactionIn, store, created_at: str | None = None, queue_investigation: bool = False) -> dict:
    """Scores and saves a payment; opens a case if the rules hold it.

    queue_investigation marks a new case as waiting for the investigation
    agent; the caller is responsible for actually starting it.
    """
    context = build_customer_context(txn, store)
    result = score_transaction(txn, resolve_payee_stats(txn, store), context)
    decision = result.pop("_decision")
    created_at = created_at or now_iso()

    record = {
        **txn.model_dump(exclude={*PAYEE_STAT_FIELDS, "investigate"}),
        **result,
        "customer_context": context,
        "created_at": created_at,
        "case_id": None,
    }

    if decision.create_case:
        case = store.create_case({
            "transaction_id": txn.transaction_id,
            "sender_id": txn.sender_id,
            "payee_id": txn.payee_id,
            "amount": txn.amount,
            "type": txn.type,
            "probability": result["probability"],
            "tier": decision.tier,
            "action": decision.action,
            "payment_status": decision.payment_status,
            "status": "escalated" if decision.escalate else "open",
            "chat_required": decision.start_chat,
            "risk_factors": result["risk_factors"],
            "payee_stats": result["payee_stats"],
            "customer_context": context,
            "tier_source": result["tier_source"],
            "reason": decision.reason,
            "scam_signals": [],  # filled in by the customer protection agent
            "investigation": None,  # filled in by the investigation agent
            # not_started | queued | running | complete | failed
            "investigation_status": "queued" if queue_investigation else "not_started",
            "created_at": created_at,
            # Every automated decision is logged on the case for audit.
            "audit_log": [
                {
                    "at": created_at,
                    "actor": "risk_model",
                    "event": "scored",
                    "detail": f"Risk score {result['probability']} (model trained {result['model_trained_on']}).",
                },
                {
                    "at": created_at,
                    "actor": "rule_engine",
                    "event": decision.action,
                    "detail": decision.reason,
                },
            ],
        })
        record["case_id"] = case["case_id"]

    store.add_transaction(record)
    return record


# --- Customer decisions on their own payment ----------------------------------
# These are fixed rules, not model output: a customer may always cancel their
# own payment, and confirming a Medium-tier check releases it (tier table).

def _log(case: dict, actor: str, event: str, detail: str) -> None:
    case["audit_log"].append({"at": now_iso(), "actor": actor, "event": event, "detail": detail})


def cancel_payment(case: dict, store) -> dict:
    """The customer cancels a held or paused payment. The money stays put."""
    if case["payment_status"] not in ("held", "safety_paused"):
        raise ValueError(f"Payment is {case['payment_status']} and cannot be cancelled")
    case.update({"payment_status": "cancelled", "action": "cancelled_by_customer", "status": "closed"})
    _log(case, "customer", "payment_cancelled", "Customer cancelled the payment. No money was sent.")
    store.save_case(case)

    transaction = store.get_transaction(case["transaction_id"])
    transaction.update({"payment_status": "cancelled", "action": "cancelled_by_customer"})
    store.add_transaction(transaction)

    chat = store.get_chat(case["case_id"])
    if chat is not None and chat["status"] != "closed":
        chat["status"] = "closed"
        store.save_chat(chat)
    return case


def verify_payment(transaction: dict, confirmed: bool, store) -> dict:
    """The customer answers a Medium-tier "was this you?" check."""
    if transaction["payment_status"] != "pending_verification":
        raise ValueError(f"Payment is {transaction['payment_status']} and is not waiting for verification")
    if confirmed:
        transaction.update({"payment_status": "allowed", "action": "allowed_after_verification"})
    else:
        transaction.update({"payment_status": "blocked", "action": "blocked_by_customer"})
    transaction["verified_at"] = now_iso()
    store.add_transaction(transaction)
    return transaction


# --- Analyst decision --------------------------------------------------------------

def apply_analyst_decision(case: dict, decision: str, reason: str, analyst: str, store) -> dict:
    """Records an analyst's decision, updates the payment, and stores feedback.

    Raises ValueError if the rules do not allow the decision right now.
    Returns the feedback record.
    """
    blocked = analyst_decision_blocked(decision, case)
    if blocked:
        raise ValueError(blocked)

    outcome = ANALYST_DECISIONS[decision]
    decided_at = now_iso()
    case.update({
        "payment_status": outcome["payment_status"],
        "action": f"analyst_{decision}",
        "status": "closed",
        "analyst_decision": {"decision": decision, "reason": reason, "analyst": analyst, "at": decided_at},
    })
    _log(case, f"analyst:{analyst}", f"decision_{decision}", f"{outcome['summary']} Reason: {reason}")
    store.save_case(case)

    transaction = store.get_transaction(case["transaction_id"])
    transaction.update({"payment_status": outcome["payment_status"], "action": f"analyst_{decision}"})
    store.add_transaction(transaction)

    chat = store.get_chat(case["case_id"])
    if chat is not None and chat["status"] != "closed":
        chat["status"] = "closed"
        store.save_chat(chat)

    # The label plus what the system knew at the time: the training example a
    # later model version would learn from.
    feedback = {
        "feedback_id": f"FB-{case['case_id']}",
        "case_id": case["case_id"],
        "transaction_id": case["transaction_id"],
        "decision": decision,
        "label_is_fraud": outcome["is_fraud"],
        "false_positive": outcome["false_positive"],
        "reason": reason,
        "analyst": analyst,
        "decided_at": decided_at,
        "model_probability": case["probability"],
        "tier": case["tier"],
        "tier_source": case["tier_source"],
        "features": {factor["feature"]: factor["value"] for factor in case["risk_factors"]},
        "scam_signal_types": [signal["type"] for signal in case["scam_signals"]],
        "customer_denied_payment": case.get("customer_denied_payment", False),
    }
    return store.add_feedback(feedback)
