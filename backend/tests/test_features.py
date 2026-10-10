"""Feature engineering must only use information from before the transaction."""

import pandas as pd

from ml.features import FEATURES, RATIO_CAP, add_history_features, compute_row_features


def make_transactions() -> pd.DataFrame:
    rows = [
        # step, type, amount, nameOrig, oldbalanceOrg, nameDest, oldbalanceDest
        (1, "TRANSFER", 100.0, "A", 100.0, "P", 0.0),
        (1, "TRANSFER", 50.0, "B", 500.0, "P", 0.0),
        (2, "PAYMENT", 30.0, "C", 0.0, "P", 0.0),
        (2, "CASH_IN", 999.0, "D", 10.0, "Q", 0.0),
        (3, "TRANSFER", 10.0, "E", 40.0, "Q", 0.0),
        (30, "CASH_OUT", 5.0, "F", 50.0, "P", 0.0),
    ]
    columns = ["step", "type", "amount", "nameOrig", "oldbalanceOrg", "nameDest", "oldbalanceDest"]
    return pd.DataFrame(rows, columns=columns)


def test_payee_history_uses_only_earlier_steps():
    out = add_history_features(make_transactions())

    # Step 1: nothing has happened yet, and the other step-1 payment to P is
    # in the same hour, so it must not be visible.
    assert out.loc[0, "payee_distinct_senders_before"] == 0
    assert out.loc[1, "payee_distinct_senders_before"] == 0
    assert out.loc[1, "payee_inflow_amount_24h"] == 0

    # Step 2: both step-1 payments to P are now history.
    assert out.loc[2, "payee_distinct_senders_before"] == 2
    assert out.loc[2, "payee_inflow_count_24h"] == 2
    assert out.loc[2, "payee_inflow_amount_24h"] == 150.0


def test_cash_in_is_not_a_payee_inflow():
    out = add_history_features(make_transactions())
    # The only earlier transaction naming Q is a CASH_IN, where money flows
    # to the originator, so Q has received nothing.
    assert out.loc[4, "payee_distinct_senders_before"] == 0
    assert out.loc[4, "payee_inflow_count_24h"] == 0


def test_24_step_window_expires():
    out = add_history_features(make_transactions())
    # At step 30 the window is steps 6-29: P's earlier inflows are too old,
    # but its three earlier senders still count.
    assert out.loc[5, "payee_inflow_count_24h"] == 0
    assert out.loc[5, "payee_inflow_amount_24h"] == 0
    assert out.loc[5, "payee_distinct_senders_before"] == 3


def test_row_features():
    features = compute_row_features(add_history_features(make_transactions()))
    assert list(features.columns) == FEATURES
    assert features.loc[0, "amount_to_balance_ratio"] == 1.0   # 100 of 100
    assert features.loc[1, "amount_to_balance_ratio"] == 0.1   # 50 of 500
    assert features.loc[2, "amount_to_balance_ratio"] == RATIO_CAP  # zero balance
    assert features.loc[0, "type_is_transfer"] == 1
    assert features.loc[5, "type_is_transfer"] == 0
    assert features.loc[5, "hour_of_day"] == 6  # step 30 -> 06:00
