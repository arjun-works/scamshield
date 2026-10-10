"""Scores one payment: model risk score + SHAP factors + rule decision."""

from functools import lru_cache

import pandas as pd

from app.schemas import TransactionIn
from ml.explain import explain, load_model, predict
from ml.features import compute_row_features
from rules.rules import decide, tier_for_score

PAYEE_STAT_FIELDS = ["payee_distinct_senders_before", "payee_inflow_count_24h", "payee_inflow_amount_24h"]


@lru_cache
def get_model():
    """Loads the model once per process."""
    return load_model()


def resolve_payee_stats(txn: TransactionIn, store) -> dict:
    """Payee history from the request if given, otherwise from stored transactions."""
    stats = store.payee_stats(txn.payee_id, txn.step)
    for field in PAYEE_STAT_FIELDS:
        if getattr(txn, field) is not None:
            stats[field] = getattr(txn, field)
    return stats


def score_transaction(txn: TransactionIn, payee_stats: dict, customer_context: dict | None = None) -> dict:
    booster, config = get_model()
    in_scope = txn.type in config["model_types"]

    probability, risk_factors = 0.0, []
    if in_scope:
        # Same column names and feature code as in training.
        row = {
            "step": txn.step,
            "type": txn.type,
            "amount": txn.amount,
            "oldbalanceOrg": txn.sender_balance_before,
            "oldbalanceDest": txn.payee_balance_before,
            **payee_stats,
        }
        features = compute_row_features(pd.DataFrame([row]))
        probability = round(predict(booster, features)[0], 4)
        risk_factors = explain(booster, features, top_n=5)[0]

    # The rule engine, not the model, picks the action.
    model_tier = tier_for_score(probability, config["tier_thresholds"]) if in_scope else "Low"
    decision = decide(
        probability, config["tier_thresholds"], in_model_scope=in_scope,
        payment_type=txn.type, customer_context=customer_context,
    )
    reason = decision.reason
    if not in_scope and decision.tier == "Low":
        reason = f"{txn.type} payments are outside the model's scope and are treated as Low risk by rule."

    return {
        "transaction_id": txn.transaction_id,
        "probability": probability,
        "tier": decision.tier,
        # "model" when the tier comes from the score, "behaviour_rule" when raised by the rule.
        "tier_source": "model" if decision.tier == model_tier else "behaviour_rule",
        "action": decision.action,
        "payment_status": decision.payment_status,
        "reason": reason,
        "in_model_scope": in_scope,
        "risk_factors": risk_factors,
        "payee_stats": payee_stats,
        "model_trained_on": config["trained_on"],
        # Not part of the API response; used by the caller.
        "_decision": decision,
    }
