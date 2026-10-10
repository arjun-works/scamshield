"""Loads the trained model and explains scores with SHAP in plain English."""

import json
from pathlib import Path

import pandas as pd
import shap
import xgboost as xgb

from ml.features import FEATURE_LABELS, FEATURES

ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"
MODEL_PATH = ARTIFACTS_DIR / "model.json"
CONFIG_PATH = ARTIFACTS_DIR / "feature_config.json"


def load_model() -> tuple[xgb.Booster, dict]:
    """Returns the trained booster and its feature config (thresholds etc.)."""
    booster = xgb.Booster()
    booster.load_model(MODEL_PATH)
    config = json.loads(CONFIG_PATH.read_text())
    return booster, config


def predict(booster: xgb.Booster, features: pd.DataFrame) -> list[float]:
    """Risk score between 0 and 1 for each row of features."""
    return booster.predict(xgb.DMatrix(features[FEATURES])).tolist()


def _money(value: float) -> str:
    return f"{value:,.0f}"


def describe_value(feature: str, value: float) -> str:
    """One plain-English sentence stating a feature's actual value."""
    if feature == "amount":
        return f"The payment amount is {_money(value)}."
    if feature == "type_is_transfer":
        return "The payment is a transfer to another account." if value else "The payment is a cash-out."
    if feature == "hour_of_day":
        return f"The payment was made at around {int(value):02d}:00."
    if feature == "sender_balance_before":
        return f"The sender's balance before the payment was {_money(value)}."
    if feature == "amount_to_balance_ratio":
        if value >= 100:
            return "The amount is far larger than the sender's available balance."
        return f"The payment moves {value:.0%} of the sender's balance."
    if feature == "payee_balance_before":
        return f"The payee's balance before the payment was {_money(value)}."
    if feature == "payee_distinct_senders_before":
        return f"{int(value)} different people have paid this payee before."
    if feature == "payee_inflow_count_24h":
        return f"The payee received {int(value)} payments in the last 24 hours."
    if feature == "payee_inflow_amount_24h":
        return f"The payee received {_money(value)} in the last 24 hours."
    return f"{FEATURE_LABELS.get(feature, feature)} is {value}."


_explainers: dict[int, shap.TreeExplainer] = {}


def _explainer_for(booster: xgb.Booster) -> shap.TreeExplainer:
    """Builds the SHAP explainer once per loaded model (it is slow to create)."""
    if id(booster) not in _explainers:
        _explainers[id(booster)] = shap.TreeExplainer(booster)
    return _explainers[id(booster)]


def explain(booster: xgb.Booster, features: pd.DataFrame, top_n: int = 5) -> list[list[dict]]:
    """Top SHAP factors for each row, largest absolute impact first.

    shap_value is in log-odds units: positive pushes the score towards fraud,
    negative towards genuine. Every sentence states a real feature value, so
    explanations stay grounded in the data.
    """
    shap_values = _explainer_for(booster).shap_values(features[FEATURES])

    results = []
    for row_values, row_shap in zip(features[FEATURES].to_numpy(), shap_values):
        factors = [
            {
                "feature": name,
                "label": FEATURE_LABELS[name],
                "value": float(value),
                "shap_value": round(float(impact), 4),
                "direction": "increases risk" if impact > 0 else "decreases risk",
                "text": describe_value(name, float(value)),
            }
            for name, value, impact in zip(FEATURES, row_values, row_shap)
        ]
        factors.sort(key=lambda f: abs(f["shap_value"]), reverse=True)
        results.append(factors[:top_n])
    return results
