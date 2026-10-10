"""Feature engineering for the ScamShield risk model (PaySim data).

Every feature uses only information available BEFORE the transaction is
executed. Post-transaction balances and the dataset's own rule flag are never
loaded (see LEAKY_COLUMNS).

The same compute_row_features() is used for training and for live scoring, so
there is a single definition of each feature.
"""

from pathlib import Path

import numpy as np
import pandas as pd

# Columns that reveal the outcome of the transaction. Never loaded.
LEAKY_COLUMNS = ["newbalanceOrig", "newbalanceDest", "isFlaggedFraud"]

RAW_COLUMNS = [
    "step", "type", "amount", "nameOrig", "oldbalanceOrg",
    "nameDest", "oldbalanceDest", "isFraud",
]

# Fraud in PaySim only happens in these types, so the model is trained on them.
# Other types are out of the model's scope and handled by a rule (Low risk).
MODEL_TYPES = ["TRANSFER", "CASH_OUT"]

# Types where money flows INTO nameDest. (In CASH_IN the money flows the other
# way, into nameOrig, so it is not counted as a payee inflow.)
INFLOW_TYPES = ["TRANSFER", "CASH_OUT", "PAYMENT", "DEBIT"]

PAYEE_WINDOW_STEPS = 24  # one step = one hour
RATIO_CAP = 100.0        # cap for amount / balance when the balance is tiny or zero

# Model inputs, in order.
FEATURES = [
    "amount",
    "type_is_transfer",
    "hour_of_day",
    "sender_balance_before",
    "amount_to_balance_ratio",
    "payee_balance_before",
    "payee_distinct_senders_before",
    "payee_inflow_count_24h",
    "payee_inflow_amount_24h",
]

# Human-readable names, used for SHAP factors shown to analysts and to Gemini.
FEATURE_LABELS = {
    "amount": "Payment amount",
    "type_is_transfer": "Payment type (transfer vs cash-out)",
    "hour_of_day": "Hour of day",
    "sender_balance_before": "Sender's balance before the payment",
    "amount_to_balance_ratio": "Share of the sender's balance being moved",
    "payee_balance_before": "Payee's balance before the payment",
    "payee_distinct_senders_before": "Number of different people who paid this payee before",
    "payee_inflow_count_24h": "Payments received by this payee in the last 24 hours",
    "payee_inflow_amount_24h": "Money received by this payee in the last 24 hours",
}

# Computed and reported, but not a model input: PaySim has no repeat
# sender-payee pairs, so it is the same value on every row.
EXCLUDED_FEATURES = ["is_first_payment_to_payee"]


def find_paysim_csv(data_dir: Path) -> Path:
    """Returns the PaySim CSV in data_dir (the file name varies by download)."""
    for path in sorted(data_dir.glob("*.csv"), key=lambda p: p.stat().st_size, reverse=True):
        header = path.open().readline().strip().split(",")
        if set(RAW_COLUMNS) <= set(header):
            return path
    raise FileNotFoundError(f"No PaySim CSV with the expected columns in {data_dir}")


def load_paysim(data_dir: Path) -> pd.DataFrame:
    """Loads PaySim without the leaky columns, sorted by step (time)."""
    path = find_paysim_csv(data_dir)
    df = pd.read_csv(path, usecols=RAW_COLUMNS)
    if not df["step"].is_monotonic_increasing:
        df = df.sort_values("step", kind="stable").reset_index(drop=True)
    return df


def add_history_features(df: pd.DataFrame) -> pd.DataFrame:
    """Adds payee and sender-payee history columns to the full dataset.

    df must contain ALL transaction types and be sorted by step. History only
    counts transactions from strictly earlier steps: the order of transactions
    inside one step (hour) is unknown, so same-step rows are treated as not yet
    visible. That makes the features slightly stale but leak-free.
    """
    step = df["step"].to_numpy(dtype=np.int64)
    amount = df["amount"].to_numpy()
    dest_id, dest_names = pd.factorize(df["nameDest"])
    orig_id, _ = pd.factorize(df["nameOrig"])
    dest_id = dest_id.astype(np.int64)

    # One integer per (sender, payee) pair.
    pair_key = orig_id.astype(np.int64) * len(dest_names) + dest_id
    # The step at which each pair first appears (df is sorted by step).
    first_step_of_pair = pd.Series(step).groupby(pair_key).transform("first").to_numpy()
    first_row_of_pair = ~pd.Series(pair_key).duplicated().to_numpy()

    # Sort the inflow rows by (payee, step) so that each payee's history is a
    # contiguous, time-ordered block. Prefix sums over that order turn "sum
    # over a step range for one payee" into two binary searches.
    step_base = int(step.max()) + 1
    key = dest_id * step_base + step
    inflow = df["type"].isin(INFLOW_TYPES).to_numpy()
    order = np.argsort(key[inflow], kind="stable")
    sorted_key = key[inflow][order]
    prefix_amount = np.concatenate([[0.0], np.cumsum(amount[inflow][order])])
    prefix_new_sender = np.concatenate([[0], np.cumsum(first_row_of_pair[inflow][order])])

    payee_start = np.searchsorted(sorted_key, dest_id * step_base, side="left")
    window_start = np.searchsorted(
        sorted_key, dest_id * step_base + np.maximum(step - PAYEE_WINDOW_STEPS, 0), side="left"
    )
    before_now = np.searchsorted(sorted_key, key, side="left")  # strictly earlier steps

    out = df.copy()
    out["payee_distinct_senders_before"] = prefix_new_sender[before_now] - prefix_new_sender[payee_start]
    out["payee_inflow_count_24h"] = before_now - window_start
    out["payee_inflow_amount_24h"] = prefix_amount[before_now] - prefix_amount[window_start]
    out["is_first_payment_to_payee"] = (first_step_of_pair == step).astype(np.int8)
    return out


def compute_row_features(df: pd.DataFrame) -> pd.DataFrame:
    """Builds the model input columns (FEATURES) for each row of df.

    df needs: step, type, amount, oldbalanceOrg, oldbalanceDest and the three
    payee_* history columns. Used both in training and in live scoring.
    """
    balance = df["oldbalanceOrg"].to_numpy(dtype=float)
    amount = df["amount"].to_numpy(dtype=float)
    # Balance of zero (or near zero) would divide by zero: use the cap instead.
    ratio = np.full(len(df), RATIO_CAP)
    np.divide(amount, balance, out=ratio, where=balance > 0)

    features = pd.DataFrame(index=df.index)
    features["amount"] = amount
    features["type_is_transfer"] = (df["type"] == "TRANSFER").astype(np.int8)
    features["hour_of_day"] = df["step"] % 24
    features["sender_balance_before"] = balance
    features["amount_to_balance_ratio"] = np.minimum(ratio, RATIO_CAP)
    features["payee_balance_before"] = df["oldbalanceDest"].astype(float)
    features["payee_distinct_senders_before"] = df["payee_distinct_senders_before"]
    features["payee_inflow_count_24h"] = df["payee_inflow_count_24h"]
    features["payee_inflow_amount_24h"] = df["payee_inflow_amount_24h"].astype(float)
    return features[FEATURES]
