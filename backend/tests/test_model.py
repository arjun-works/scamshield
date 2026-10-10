"""Sanity checks on the trained model artifacts (run ml.train first)."""

import pandas as pd
import pytest

from ml.explain import MODEL_PATH, explain, load_model, predict
from ml.features import FEATURE_LABELS, FEATURES, compute_row_features

pytestmark = pytest.mark.skipif(not MODEL_PATH.exists(), reason="model not trained yet")


def one_payment(amount: float, balance: float, payment_type: str = "TRANSFER") -> pd.DataFrame:
    """A single payment to a payee with no history, as model features."""
    row = {
        "step": 14, "type": payment_type, "amount": amount,
        "oldbalanceOrg": balance, "oldbalanceDest": 0.0,
        "payee_distinct_senders_before": 0, "payee_inflow_count_24h": 0,
        "payee_inflow_amount_24h": 0.0,
    }
    return compute_row_features(pd.DataFrame([row]))


def test_config_matches_code():
    _, config = load_model()
    assert config["features"] == FEATURES
    thresholds = config["tier_thresholds"]
    assert 0 < thresholds["medium"] < thresholds["high"] < thresholds["critical"] < 1


def test_draining_the_account_scores_high_and_small_payment_scores_low():
    booster, config = load_model()
    drained = predict(booster, one_payment(amount=450_000, balance=450_000))[0]
    small = predict(booster, one_payment(amount=2_000, balance=450_000))[0]
    assert drained >= config["tier_thresholds"]["high"]
    assert small < config["tier_thresholds"]["medium"]


def test_explanation_is_grounded_in_feature_values():
    booster, _ = load_model()
    factors = explain(booster, one_payment(amount=450_000, balance=450_000), top_n=3)[0]
    assert len(factors) == 3
    top = factors[0]
    assert top["feature"] == "amount_to_balance_ratio"
    assert top["label"] == FEATURE_LABELS["amount_to_balance_ratio"]
    assert top["direction"] == "increases risk"
    assert "100%" in top["text"]
