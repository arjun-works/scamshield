"""Tools the investigation agent can call.

Each tool reads stored facts and returns them as plain data. The agent has no
tool that holds, releases or rejects a payment: money actions belong to the
rule engine and the analyst.

ADK passes `tool_context` automatically; tests call the tools without it.
"""

from statistics import median

from agents.policy import load_sections, search_policy
from agents.schemas import InvestigationCase
from db.store import get_store, now_iso

EVIDENCE_TOOLS = ["score_transaction", "get_customer_history", "get_payee_profile", "find_similar_cases", "get_policy"]


def _record_call(tool_context, name: str) -> None:
    """Remembers which tools ran in this investigation (for the audit log)."""
    if tool_context is not None:
        tool_context.state["tools_called"] = [*tool_context.state.get("tools_called", []), name]


def _transaction_brief(txn: dict) -> dict:
    return {
        "transaction_id": txn["transaction_id"],
        "created_at": txn["created_at"],
        "type": txn["type"],
        "amount": txn["amount"],
        "sender_id": txn["sender_id"],
        "sender_balance_before": txn["sender_balance_before"],
        "payee_id": txn["payee_id"],
        "payee_balance_before": txn["payee_balance_before"],
        "description": txn.get("description"),
    }


def score_transaction(transaction_id: str, tool_context=None) -> dict:
    """Returns the payment's details, the risk model's score, the tier and
    action chosen by the rule engine, and the top SHAP risk factors.

    Args:
        transaction_id: ID of the flagged transaction.
    """
    _record_call(tool_context, "score_transaction")
    txn = get_store().get_transaction(transaction_id)
    if txn is None:
        return {"status": "error", "message": f"Transaction {transaction_id} not found."}
    return {
        "status": "ok",
        "transaction": _transaction_brief(txn),
        "risk_score": txn["probability"],
        "tier": txn["tier"],
        "tier_source": txn["tier_source"],
        "action_taken_by_rule_engine": txn["action"],
        "rule_engine_reason": txn["reason"],
        "in_model_scope": txn["in_model_scope"],
        "risk_factors": [
            {"factor": f["text"], "effect": f["direction"], "shap_value": f["shap_value"]}
            for f in txn["risk_factors"]
        ],
    }


def get_customer_history(customer_id: str, tool_context=None) -> dict:
    """Returns the sender's profile and recent payment history.

    Args:
        customer_id: The sender_id of the transaction.
    """
    _record_call(tool_context, "get_customer_history")
    store = get_store()
    customer = store.get_customer(customer_id)
    everything = store.list_transactions(limit=200, sender_id=customer_id)
    # History means completed payments. Held or unverified ones (including the
    # payment under investigation) are counted separately.
    history = [t for t in everything if t["payment_status"] == "allowed"]
    not_completed = len(everything) - len(history)
    if customer is None:
        return {
            "status": "ok",
            "known_customer": False,
            "note": "No profile is held for this sender. Customer history is not known.",
            "completed_payments_on_record": len(history),
            "held_or_unverified_payments": not_completed,
        }

    payee_names = {p["payee_id"]: p["name"] for p in customer["usual_payees"]}
    amounts = [t["amount"] for t in history]
    return {
        "status": "ok",
        "known_customer": True,
        "data_source": "synthetic customer profile",
        "profile": {
            "name": customer["name"],
            "preferred_language": customer["preferred_language"],
            "segment": customer["segment"],
            "city": customer["city"],
            "member_since": customer["member_since"],
            "typical_amount_min": customer["typical_amount_min"],
            "typical_amount_max": customer["typical_amount_max"],
            "usual_payees": [{"payee_id": pid, "name": name} for pid, name in payee_names.items()],
        },
        "completed_payments_on_record": len(history),
        "held_or_unverified_payments": not_completed,
        "median_completed_amount": median(amounts) if amounts else None,
        "largest_completed_amount": max(amounts) if amounts else None,
        "recent_completed_payments": [
            {
                "date": t["created_at"][:10],
                "type": t["type"],
                "amount": t["amount"],
                "payee_id": t["payee_id"],
                "payee_name": payee_names.get(t["payee_id"]),
                "tier": t["tier"],
            }
            for t in history[:10]
        ],
    }


def get_payee_profile(payee_id: str, transaction_id: str, tool_context=None) -> dict:
    """Returns what is known about the receiving account, including mule
    indicators (see policy POL-4.1).

    Args:
        payee_id: The payee_id of the transaction.
        transaction_id: ID of the flagged transaction.
    """
    _record_call(tool_context, "get_payee_profile")
    store = get_store()
    txn = store.get_transaction(transaction_id)
    if txn is None:
        return {"status": "error", "message": f"Transaction {transaction_id} not found."}

    stats = txn["payee_stats"]
    context = txn.get("customer_context", {})
    other_cases = [
        c for c in store.list_cases(limit=500)
        if c["payee_id"] == payee_id and c["transaction_id"] != transaction_id
    ]

    # Plain statements of fact, so the agent does not have to infer them.
    indicators = []
    if stats["payee_distinct_senders_before"] == 0:
        indicators.append("No earlier payments to this payee are on record: it is new to the bank's data.")
    else:
        indicators.append(f"{stats['payee_distinct_senders_before']} different senders paid this payee before.")
    if stats["payee_inflow_count_24h"]:
        indicators.append(
            f"The payee received {stats['payee_inflow_count_24h']} payments totalling "
            f"{stats['payee_inflow_amount_24h']:,.0f} in the 24 hours before this payment."
        )
    else:
        indicators.append("The payee received no payments in the 24 hours before this payment.")
    if txn["payee_balance_before"] == 0:
        indicators.append("The payee's balance was zero before this payment.")
    if other_cases:
        indicators.append(f"{len(other_cases)} other case(s) name this payee.")
    if context.get("known_customer"):
        indicators.append(
            "The sender has never paid this payee before." if context.get("is_new_payee")
            else "The sender has paid this payee before or lists it as a usual payee."
        )

    return {
        "status": "ok",
        "payee_id": payee_id,
        "payee_name_in_sender_profile": context.get("payee_name"),
        "payee_balance_before": txn["payee_balance_before"],
        "distinct_senders_before": stats["payee_distinct_senders_before"],
        "payments_received_last_24h": stats["payee_inflow_count_24h"],
        "amount_received_last_24h": stats["payee_inflow_amount_24h"],
        "other_cases_naming_payee": [c["case_id"] for c in other_cases],
        "facts": indicators,
    }


def find_similar_cases(transaction_id: str, tool_context=None) -> dict:
    """Returns earlier cases that resemble this one: same payee, same sender,
    or the same payment type and tier with a similar amount.

    Args:
        transaction_id: ID of the flagged transaction.
    """
    _record_call(tool_context, "find_similar_cases")
    store = get_store()
    txn = store.get_transaction(transaction_id)
    if txn is None:
        return {"status": "error", "message": f"Transaction {transaction_id} not found."}

    similar = []
    for case in store.list_cases(limit=500):
        if case["transaction_id"] == transaction_id:
            continue
        if case["payee_id"] == txn["payee_id"]:
            why = "same payee"
        elif case["sender_id"] == txn["sender_id"]:
            why = "same sender"
        elif case["type"] == txn["type"] and case["tier"] == txn["tier"] and 0.5 <= case["amount"] / txn["amount"] <= 2:
            why = "same payment type and tier, similar amount"
        else:
            continue
        similar.append({
            "case_id": case["case_id"],
            "why_similar": why,
            "tier": case["tier"],
            "type": case["type"],
            "amount": case["amount"],
            "status": case["status"],
            "analyst_decision": case.get("analyst_decision"),
            "summary": (case.get("investigation") or {}).get("investigation_summary"),
        })
    return {"status": "ok", "similar_cases": similar[:5], "total_found": len(similar)}


def get_policy(topic: str, tool_context=None) -> dict:
    """Returns sections of the bank's fraud and scam handling policy.

    Args:
        topic: A section ID such as "POL-4" or "POL-2.10", or keywords such as
            "mule account", "account takeover" or "escalation".
    """
    _record_call(tool_context, "get_policy")
    sections = search_policy(topic)
    if not sections:
        return {"status": "ok", "sections": [], "note": "No matching section. Try other keywords or a POL-x ID."}
    return {"status": "ok", "sections": sections}


def create_case(
    transaction_id: str,
    top_risk_factors: list[str],
    historical_evidence: list[str],
    payee_mule_evidence: list[str],
    policy_references: list[str],
    recommended_next_step: str,
    investigation_summary: str,
    tool_context=None,
) -> dict:
    """Writes the investigation to the case file. Call exactly once, last.

    Args:
        transaction_id: ID of the flagged transaction.
        top_risk_factors: The main risk factors in plain English, most important first.
        historical_evidence: What the customer's history shows about this payment.
        payee_mule_evidence: What the payee's history shows, including any mule indicators.
        policy_references: Policy section IDs that apply, for example ["POL-2.10", "POL-4.1"].
        recommended_next_step: Advice for the analyst on what to check or do next.
        investigation_summary: Three to five sentences summarising the case.
    """
    store = get_store()
    txn = store.get_transaction(transaction_id)
    case = store.get_case(txn["case_id"]) if txn and txn.get("case_id") else None
    if case is None:
        return {"status": "error", "message": f"No open case for transaction {transaction_id}."}

    state = tool_context.state if tool_context is not None else {}
    tools_called = list(state.get("tools_called", []))
    if tool_context is not None:
        if state.get("transaction_id") != transaction_id:
            return {"status": "error", "message": f"This investigation is for {state.get('transaction_id')}."}
        missing = [name for name in EVIDENCE_TOOLS if name not in tools_called]
        if missing:
            return {"status": "error", "message": f"Gather evidence first. Tools not yet called: {missing}."}

    # Only policy sections that really exist may be cited.
    sections = load_sections()
    cited = [ref.strip().upper() for ref in policy_references]
    valid = [{"section": ref, "title": sections[ref]["title"]} for ref in dict.fromkeys(cited) if ref in sections]
    unknown = [ref for ref in cited if ref not in sections]
    if not valid:
        return {"status": "error", "message": f"None of {cited} is a policy section. Use IDs returned by get_policy."}

    try:
        investigation = InvestigationCase(
            case_id=case["case_id"],
            # Facts come from stored data, not from the model.
            transaction=_transaction_brief(txn),
            probability=txn["probability"],
            tier=txn["tier"],
            tier_source=txn["tier_source"],
            top_risk_factors=top_risk_factors,
            historical_evidence=historical_evidence,
            payee_mule_evidence=payee_mule_evidence,
            policy_references=valid,
            recommended_next_step=recommended_next_step,
            investigation_summary=investigation_summary,
            scam_signals=case.get("scam_signals", []),
            model=state.get("model", "unknown"),
            tools_called=tools_called,
            generated_at=now_iso(),
        )
    except ValueError as exc:
        return {"status": "error", "message": f"Case file is incomplete: {exc}"}

    detail = f"Investigation written by {investigation.model} after calling {', '.join(tools_called) or 'no tools'}."
    if unknown:
        detail += f" Dropped unknown policy references: {unknown}."
    case["investigation"] = investigation.model_dump()
    case["investigation_status"] = "complete"
    case["audit_log"].append({
        "at": investigation.generated_at,
        "actor": "investigation_agent",
        "event": "investigation_written",
        "detail": detail,
    })
    store.save_case(case)

    if tool_context is not None:
        # The case file is the final output: no extra model call to summarise it.
        tool_context.actions.skip_summarization = True
    return {"status": "ok", "case_id": case["case_id"]}
