"""Trains the ScamShield risk model on PaySim and writes the model, config and metrics.

Run from the backend/ folder:
    uv run python -m ml.train

Outputs:
    backend/ml/artifacts/model.json           XGBoost model
    backend/ml/artifacts/feature_config.json  features, labels, tier thresholds
    docs/model_metrics.md                     metrics report
    data/test_scored.pkl                      scored test set (gitignored; used by
                                              the notebook and the simulator)
"""

import json
import math
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import shap
import xgboost as xgb
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score

from ml.features import (
    EXCLUDED_FEATURES, FEATURE_LABELS, FEATURES, INFLOW_TYPES, LEAKY_COLUMNS,
    MODEL_TYPES, PAYEE_WINDOW_STEPS, RATIO_CAP, add_history_features,
    compute_row_features, load_paysim,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"
METRICS_PATH = REPO_ROOT / "docs" / "model_metrics.md"

# Time-based split: train on the earliest 70% of rows, validate on the next
# 10%, test on the latest 20%. Boundaries are whole steps, so no step is split.
TRAIN_FRACTION = 0.70
VALID_FRACTION = 0.10

# Tier thresholds are picked on the validation set (never on the test set):
# the lowest score at which precision reaches each target. The costlier the
# action for a genuine customer, the higher the precision it must reach.
TIER_PRECISION = {"medium": 0.25, "high": 0.50, "critical": 0.95}

REPORT_THRESHOLDS = [0.01, 0.05, 0.10, 0.20, 0.30, 0.50, 0.70, 0.80, 0.90, 0.95, 0.99]
SEED = 42


def split_steps(steps: pd.Series) -> tuple[int, int]:
    """Last step of the train set and last step of the validation set."""
    cumulative = steps.value_counts().sort_index().cumsum() / len(steps)
    train_end = int(cumulative[cumulative >= TRAIN_FRACTION].index[0])
    valid_end = int(cumulative[cumulative >= TRAIN_FRACTION + VALID_FRACTION].index[0])
    return train_end, valid_end


def fit_model(x_train, y_train, x_valid, y_valid, scale_pos_weight) -> xgb.Booster:
    """Fits XGBoost with early stopping on validation PR-AUC."""
    model = xgb.XGBClassifier(
        n_estimators=600,
        learning_rate=0.1,
        max_depth=6,
        subsample=0.8,
        colsample_bytree=0.8,
        tree_method="hist",
        # Class imbalance is handled by weighting, not by resampling.
        scale_pos_weight=scale_pos_weight,
        eval_metric="aucpr",
        early_stopping_rounds=30,
        random_state=SEED,
    )
    model.fit(x_train, y_train, eval_set=[(x_valid, y_valid)], verbose=False)
    # Keep only the trees up to the best iteration, so the saved model predicts
    # the same everywhere (plain Booster, sklearn wrapper, SHAP).
    return model.get_booster()[: model.best_iteration + 1]


def score(booster: xgb.Booster, x: pd.DataFrame) -> np.ndarray:
    return booster.predict(xgb.DMatrix(x))


def summary_metrics(y, scores) -> dict:
    return {
        "rows": int(len(y)),
        "frauds": int(y.sum()),
        "fraud_rate": float(y.mean()),
        "pr_auc": float(average_precision_score(y, scores)),
        "roc_auc": float(roc_auc_score(y, scores)),
    }


def threshold_row(y, scores, threshold: float) -> dict:
    flagged = scores >= threshold
    caught = int((flagged & (y == 1)).sum())
    return {
        "threshold": threshold,
        "flagged": int(flagged.sum()),
        "frauds_caught": caught,
        "precision": caught / max(int(flagged.sum()), 1),
        "recall": caught / max(int(y.sum()), 1),
        "false_alarms": int(flagged.sum()) - caught,
    }


def ceil2(value: float) -> float:
    """Rounds a threshold up to 2 decimals (up, so the target still holds)."""
    return min(math.ceil(value * 100) / 100, 0.99)


def pick_thresholds(y_valid, valid_scores) -> dict:
    """Chooses Medium / High / Critical thresholds on the validation set."""
    precision, _, thresholds = precision_recall_curve(y_valid, valid_scores)
    precision = precision[:-1]  # last point has no threshold

    def lowest_with_precision(target: float) -> float:
        return ceil2(float(thresholds[precision >= target].min()))

    critical = lowest_with_precision(TIER_PRECISION["critical"])
    high = min(lowest_with_precision(TIER_PRECISION["high"]), critical - 0.01)
    medium = min(lowest_with_precision(TIER_PRECISION["medium"]), high - 0.01)
    return {"medium": round(medium, 2), "high": round(high, 2), "critical": round(critical, 2)}


def assign_tier(scores: np.ndarray, thresholds: dict) -> np.ndarray:
    tiers = np.full(len(scores), "Low", dtype=object)
    tiers[scores >= thresholds["medium"]] = "Medium"
    tiers[scores >= thresholds["high"]] = "High"
    tiers[scores >= thresholds["critical"]] = "Critical"
    return tiers


def tier_table(y, scores, thresholds: dict) -> list[dict]:
    tiers = assign_tier(scores, thresholds)
    rows = []
    for tier in ["Low", "Medium", "High", "Critical"]:
        mask = tiers == tier
        frauds = int(y[mask].sum())
        rows.append({
            "tier": tier,
            "payments": int(mask.sum()),
            "share": float(mask.mean()),
            "frauds": frauds,
            "fraud_rate": frauds / max(int(mask.sum()), 1),
            "share_of_all_fraud": frauds / max(int(y.sum()), 1),
        })
    return rows


def main() -> None:
    print("Loading PaySim...")
    raw = load_paysim(DATA_DIR)

    # --- Data checks reported in the metrics file -------------------------
    sender_counts = raw["nameOrig"].value_counts()
    by_type = raw.groupby("type")["isFraud"].agg(["size", "sum"])
    data_facts = {
        "rows": int(len(raw)),
        "frauds": int(raw["isFraud"].sum()),
        "steps": [int(raw["step"].min()), int(raw["step"].max())],
        "unique_senders": int(len(sender_counts)),
        "repeat_senders": int((sender_counts > 1).sum()),
        "max_txns_per_sender": int(sender_counts.max()),
        "share_rows_from_repeat_senders": float(sender_counts[sender_counts > 1].sum() / len(raw)),
        "by_type": {t: {"rows": int(r["size"]), "frauds": int(r["sum"])} for t, r in by_type.iterrows()},
    }

    print("Building history features...")
    full = add_history_features(raw)
    data_facts["share_first_payment_to_payee"] = float(full["is_first_payment_to_payee"].mean())
    del raw

    # Model scope: only the types where fraud occurs. History features above
    # were computed on ALL types first, so payee inflows include payments etc.
    df = full[full["type"].isin(MODEL_TYPES)].reset_index(drop=True)
    del full
    drained = df["amount"] == df["oldbalanceOrg"]
    data_facts["fraud_share_draining_account"] = float(drained[df["isFraud"] == 1].mean())
    data_facts["legit_share_draining_account"] = float(drained[df["isFraud"] == 0].mean())

    train_end, valid_end = split_steps(df["step"])
    is_train = df["step"] <= train_end
    is_valid = (df["step"] > train_end) & (df["step"] <= valid_end)
    is_test = df["step"] > valid_end

    x = compute_row_features(df)
    y = df["isFraud"].to_numpy()
    x_train, y_train = x[is_train], y[is_train]
    x_valid, y_valid = x[is_valid], y[is_valid]
    x_test, y_test = x[is_test], y[is_test]

    # Class weight from the training set only. We use sqrt(negatives/positives)
    # rather than the full ratio: both give the same PR-AUC, but the full ratio
    # pushes almost every flagged payment above 0.99, which leaves no room for
    # separate risk tiers (see docs/model_metrics.md).
    class_ratio = float((y_train == 0).sum() / (y_train == 1).sum())
    scale_pos_weight = math.sqrt(class_ratio)

    # Reference run with the full ratio, for the comparison in the metrics file.
    full_weight_booster = fit_model(x_train, y_train, x_valid, y_valid, class_ratio)
    full_weight_scores = score(full_weight_booster, x_test)
    full_weight = summary_metrics(y_test, full_weight_scores)
    full_weight["class_ratio"] = class_ratio
    full_weight["at_0.90"] = threshold_row(y_test, full_weight_scores, 0.90)
    full_weight["at_0.99"] = threshold_row(y_test, full_weight_scores, 0.99)

    print(f"Training on steps 1-{train_end}, validating on {train_end + 1}-{valid_end}, "
          f"testing on {valid_end + 1}-{int(df['step'].max())}...")
    booster = fit_model(x_train, y_train, x_valid, y_valid, scale_pos_weight)

    valid_scores = score(booster, x_valid)
    test_scores = score(booster, x_test)
    thresholds = pick_thresholds(y_valid, valid_scores)

    # --- Robustness check: retrain without the two sender-balance features --
    # (PaySim fraud almost always empties the account; see the metrics file.)
    balance_features = ["amount_to_balance_ratio", "sender_balance_before"]
    reduced = [f for f in FEATURES if f not in balance_features]
    reduced_booster = fit_model(x_train[reduced], y_train, x_valid[reduced], y_valid, scale_pos_weight)
    ablation = summary_metrics(y_test, score(reduced_booster, x_test[reduced]))

    # --- SHAP: global importance on a test sample, plus one worked example --
    print("Computing SHAP values...")
    from ml.explain import explain  # local import: explain.py reads the artifacts folder

    sample = x_test.sample(n=min(50_000, len(x_test)), random_state=SEED)
    shap_values = shap.TreeExplainer(booster).shap_values(sample)
    mean_abs = np.abs(shap_values).mean(axis=0)
    importance = sorted(
        ({"feature": f, "label": FEATURE_LABELS[f], "mean_abs_shap": float(v)} for f, v in zip(FEATURES, mean_abs)),
        key=lambda r: r["mean_abs_shap"], reverse=True,
    )
    top_fraud = x_test.iloc[[int(np.argmax(np.where(y_test == 1, test_scores, -1)))]]
    example = {"score": float(score(booster, top_fraud)[0]), "factors": explain(booster, top_fraud)[0]}

    metrics = {
        "trained_on": date.today().isoformat(),
        "data": data_facts,
        "split": {
            "train_steps": [1, train_end],
            "valid_steps": [train_end + 1, valid_end],
            "test_steps": [valid_end + 1, int(df["step"].max())],
        },
        "scale_pos_weight": scale_pos_weight,
        "trees": int(booster.num_boosted_rounds()),
        "train": {"rows": int(len(y_train)), "frauds": int(y_train.sum()), "fraud_rate": float(y_train.mean())},
        "valid": summary_metrics(y_valid, valid_scores),
        "test": summary_metrics(y_test, test_scores),
        "valid_thresholds": [threshold_row(y_valid, valid_scores, t) for t in REPORT_THRESHOLDS],
        "test_thresholds": [threshold_row(y_test, test_scores, t) for t in REPORT_THRESHOLDS],
        "thresholds": thresholds,
        "valid_tier_cutoffs": [threshold_row(y_valid, valid_scores, t) for t in thresholds.values()],
        "test_at_0.90": threshold_row(y_test, test_scores, 0.90),
        "test_at_0.99": threshold_row(y_test, test_scores, 0.99),
        "valid_tiers": tier_table(y_valid, valid_scores, thresholds),
        "test_tiers": tier_table(y_test, test_scores, thresholds),
        "tier_precision_targets": TIER_PRECISION,
        "full_class_ratio_run": full_weight,
        "ablation_without_balance_features": ablation,
        "shap_importance": importance,
        "shap_example": example,
    }

    # --- Save everything ---------------------------------------------------
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    booster.save_model(ARTIFACTS_DIR / "model.json")
    config = {
        "model_file": "model.json",
        "trained_on": metrics["trained_on"],
        "features": FEATURES,
        "feature_labels": FEATURE_LABELS,
        "excluded_features": EXCLUDED_FEATURES,
        "model_types": MODEL_TYPES,
        "out_of_scope_tier": "Low",
        "inflow_types": INFLOW_TYPES,
        "payee_window_steps": PAYEE_WINDOW_STEPS,
        "ratio_cap": RATIO_CAP,
        "dropped_leaky_columns": LEAKY_COLUMNS,
        "tier_thresholds": thresholds,
        "split": metrics["split"],
        "scale_pos_weight": scale_pos_weight,
        "test_pr_auc": metrics["test"]["pr_auc"],
        "test_roc_auc": metrics["test"]["roc_auc"],
    }
    (ARTIFACTS_DIR / "feature_config.json").write_text(json.dumps(config, indent=2))
    (ARTIFACTS_DIR / "metrics.json").write_text(json.dumps(metrics, indent=2))

    from ml.report import render_metrics  # kept separate: it is only text formatting

    METRICS_PATH.write_text(render_metrics(metrics), encoding="utf-8")

    scored = df[is_test].copy()
    scored[FEATURES] = x_test
    scored["score"] = test_scores
    scored["tier"] = assign_tier(test_scores, thresholds)
    scored.to_pickle(DATA_DIR / "test_scored.pkl")

    print(f"Test PR-AUC {metrics['test']['pr_auc']:.4f}  ROC-AUC {metrics['test']['roc_auc']:.4f}")
    print(f"Tier thresholds: {thresholds}")
    print(f"Wrote {ARTIFACTS_DIR / 'model.json'}, feature_config.json, {METRICS_PATH}")


if __name__ == "__main__":
    main()
