"""Replays PaySim test-set payments to the ScamShield API at a slow rate.

Run from the repo root, with the backend running:
    uv run --project backend python scripts/simulate.py
    uv run --project backend python scripts/simulate.py --count 50 --delay 1 --fraud-share 0.3

Needs data/test_scored.pkl, which `uv run python -m ml.train` writes.
Each payment is one Firestore write (two if a case is opened), so keep --count
modest on the free tier.
"""

import argparse
import sys
import time
import uuid
from pathlib import Path

import httpx
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_SET = REPO_ROOT / "data" / "test_scored.pkl"


def pick_payments(test: pd.DataFrame, count: int, fraud_share: float, seed: int | None) -> pd.DataFrame:
    """A shuffled mix of fraud and genuine test-set payments.

    Fraud is under 1% of the data, so it is over-sampled to make the demo feed
    interesting. fraud_share is the share of fraud in the replayed payments.
    """
    n_fraud = round(count * fraud_share)
    fraud = test[test["isFraud"] == 1].sample(n_fraud, random_state=seed)
    genuine = test[test["isFraud"] == 0].sample(count - n_fraud, random_state=seed)
    return pd.concat([fraud, genuine]).sample(frac=1, random_state=seed)


def to_request(row: pd.Series, investigate: bool) -> dict:
    """Maps a PaySim row to the API's field names."""
    return {
        "investigate": investigate,
        "transaction_id": f"SIM-{uuid.uuid4().hex[:10].upper()}",
        "step": int(row["step"]),
        "type": row["type"],
        "amount": float(row["amount"]),
        "sender_id": row["nameOrig"],
        "sender_balance_before": float(row["oldbalanceOrg"]),
        "payee_id": row["nameDest"],
        "payee_balance_before": float(row["oldbalanceDest"]),
        # Payee history as it was in the dataset, so scores match the offline ones.
        "payee_distinct_senders_before": int(row["payee_distinct_senders_before"]),
        "payee_inflow_count_24h": int(row["payee_inflow_count_24h"]),
        "payee_inflow_amount_24h": float(row["payee_inflow_amount_24h"]),
        "description": "Simulated PaySim payment",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default="http://localhost:8080", help="backend base URL")
    parser.add_argument("--count", type=int, default=20, help="number of payments to send")
    parser.add_argument("--delay", type=float, default=2.0, help="seconds between payments")
    parser.add_argument("--fraud-share", type=float, default=0.2, help="share of fraud in the replay (0 to 1)")
    parser.add_argument("--seed", type=int, default=None, help="random seed for a repeatable replay")
    parser.add_argument(
        "--investigate", action="store_true",
        help="let Gemini investigate each held payment (off by default to save free-tier quota)",
    )
    args = parser.parse_args()

    if not TEST_SET.exists():
        print(f"{TEST_SET} not found. Run 'uv run python -m ml.train' in backend/ first.")
        return 1

    payments = pick_payments(pd.read_pickle(TEST_SET), args.count, args.fraud_share, args.seed)
    caught = missed = false_alarms = 0

    with httpx.Client(base_url=args.api, timeout=30) as client:
        for number, (_, row) in enumerate(payments.iterrows(), start=1):
            response = client.post("/transactions", json=to_request(row, args.investigate))
            response.raise_for_status()
            txn = response.json()["transaction"]

            is_fraud = bool(row["isFraud"])
            held = txn["payment_status"] == "held"
            caught += is_fraud and held
            missed += is_fraud and not held
            false_alarms += held and not is_fraud
            print(
                f"{number:>3}/{len(payments)}  {txn['type']:<8} {txn['amount']:>14,.2f}  "
                f"score {txn['probability']:.3f}  {txn['tier']:<8} {txn['action']:<17} "
                f"{'FRAUD' if is_fraud else 'genuine'}"
            )
            if number < len(payments):
                time.sleep(args.delay)

    print(f"\nFrauds held: {caught}   frauds not held: {missed}   genuine payments held: {false_alarms}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
