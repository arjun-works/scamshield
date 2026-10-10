"""Sets up the three demo scenarios, and resets the demo data.

Run from the repo root, with the backend running (or pass --api for Cloud Run):

    uv run --project backend python scripts/demo.py reset
    uv run --project backend python scripts/demo.py scenario 1
    uv run --project backend python scripts/demo.py scenario 2
    uv run --project backend python scripts/demo.py scenario 3            # you do the chat in the customer app
    uv run --project backend python scripts/demo.py scenario 3 --auto     # the script plays the customer

    uv run --project backend python scripts/demo.py --api https://<cloud-run-url> reset

The scenarios:
  1. A normal payment to a usual payee: allowed instantly.
  2. Account takeover into a mule account: held, escalated, investigated by Gemini.
  3. A scam victim who says "yes, it was me": the chat finds a fake police
     officer and a "digital arrest" screenshot, and the rules start a safety pause.

`reset` deletes all ScamShield data and reseeds the 30 synthetic customers. It
needs ADMIN_TOKEN (in .env or the environment) to match the backend's.
All names, accounts and messages are synthetic.
"""

import argparse
import base64
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")
SCREENSHOT = REPO_ROOT / "backend" / "tests" / "fixtures" / "screenshots" / "digital_arrest.png"

NORMAL_CUSTOMER = "CUST-001"    # Ananya Rao
TAKEOVER_CUSTOMER = "CUST-002"  # Rohan Mehta
EARLIER_VICTIM = "CUST-005"     # Sneha Kulkarni: hit by the same mule account an hour before
SCAM_CUSTOMER = "CUST-001"      # Ananya Rao, a senior citizen
MULE_ACCOUNT = "C-MULE-70231"
SCAM_ACCOUNT = "C-NEW-99417"


def current_step() -> int:
    """Same hour counter as the backend (hours since the epoch, India time)."""
    return int((time.time() + 5 * 3600 + 1800) // 3600)


def money(amount: float) -> str:
    return f"Rs {amount:,.0f}"


class Demo:
    def __init__(self, api: str) -> None:
        self.http = httpx.Client(base_url=api.rstrip("/"), timeout=180)

    def get(self, path: str) -> dict:
        response = self.http.get(path)
        response.raise_for_status()
        return response.json()

    def post(self, path: str, body: dict | None = None, **kwargs) -> dict:
        response = self.http.post(path, json=body or {}, **kwargs)
        if response.status_code >= 400:
            sys.exit(f"{path} failed ({response.status_code}): {response.json().get('detail', response.text)}")
        return response.json()

    def customer(self, customer_id: str) -> dict:
        response = self.http.get(f"/customers/{customer_id}")
        if response.status_code == 404:
            sys.exit("Demo customers not found. Run 'scripts/demo.py reset' first.")
        return response.json()["customer"]

    # --- reset ------------------------------------------------------------------

    def reset(self) -> None:
        token = os.getenv("ADMIN_TOKEN", "").strip()
        if not token:
            sys.exit("ADMIN_TOKEN is not set. Add it to .env (and to the backend) to use reset.")
        print("Deleting all ScamShield data and reseeding (up to a minute on Firestore)...")
        summary = self.post("/admin/reset", headers={"X-Admin-Token": token})
        print(f"Done: {summary['customers']} customers, {summary['transactions']} past payments, all Low.")

    # --- scenario 1 ---------------------------------------------------------------

    def scenario_1(self) -> None:
        customer = self.customer(NORMAL_CUSTOMER)
        payee = next(p for p in customer["usual_payees"] if p["category"] == "family")
        print(f"Scenario 1: {customer['name']} sends {money(2500)} to {payee['name']} (a usual payee).")
        txn = self.post("/transactions", {
            "type": "TRANSFER", "amount": 2500, "sender_id": customer["customer_id"],
            "sender_balance_before": customer["balance"], "payee_id": payee["payee_id"], "description": payee["name"],
        })["transaction"]
        print(f"  Risk score {txn['probability']:.4f} -> tier {txn['tier']} -> {txn['action'].upper()} ({txn['payment_status']}).")
        print("  Nothing for the analyst to do; it appears in the live feed as a normal payment.")

    # --- scenario 2 ---------------------------------------------------------------

    def scenario_2(self) -> None:
        customer = self.customer(TAKEOVER_CUSTOMER)
        step = current_step()
        print(f"Scenario 2: account takeover. {customer['name']}'s whole balance goes to {MULE_ACCOUNT}.")

        # First, another customer's account is emptied into the same payee an
        # hour earlier. That payment is held too, so the mule account already
        # has a case against it when the second one arrives.
        earlier = self.customer(EARLIER_VICTIM)
        first = self.post("/transactions", {
            "step": step - 1, "type": "TRANSFER", "amount": earlier["balance"], "sender_id": earlier["customer_id"],
            "sender_balance_before": earlier["balance"], "payee_id": MULE_ACCOUNT, "payee_balance_before": 0,
            "description": f"Account {MULE_ACCOUNT}", "investigate": False,
        })
        print(f"  Setting the scene: an hour ago {earlier['name']}'s balance was sent to the same account "
              f"and held ({first['transaction']['tier']}, case {first['case_id']}).")

        # Then the takeover: everything in the account, to that same payee.
        result = self.post("/transactions", {
            "step": step, "type": "TRANSFER", "amount": customer["balance"], "sender_id": customer["customer_id"],
            "sender_balance_before": customer["balance"], "payee_id": MULE_ACCOUNT, "payee_balance_before": 0,
            "description": f"Account {MULE_ACCOUNT}",
        })
        txn, case_id = result["transaction"], result["case_id"]
        print(f"  {money(txn['amount'])} -> risk score {txn['probability']:.4f} -> tier {txn['tier']} -> {txn['action'].upper()}.")
        if not case_id:
            sys.exit("  Unexpected: the payment was not held.")
        print(f"  Case {case_id} opened and escalated. Top factor: {txn['risk_factors'][0]['text']}")

        print("  Gemini is investigating", end="", flush=True)
        case = self.get(f"/cases/{case_id}")
        for _ in range(60):
            if case["investigation_status"] not in ("queued", "running"):
                break
            time.sleep(4)
            print(".", end="", flush=True)
            case = self.get(f"/cases/{case_id}")
        print()
        if case["investigation_status"] != "complete":
            print(f"  Investigation status: {case['investigation_status']}. Open the case and press 'Run investigation'.")
            return
        investigation = case["investigation"]
        print(f"  Case file written by {investigation['model']}:")
        print(f"    {investigation['investigation_summary']}")
        print(f"    Policy: {', '.join(ref['section'] for ref in investigation['policy_references'])}")
        print(f"  The payment stays {case['payment_status']}. Open the analyst console to decide: {case_id}.")

    # --- scenario 3 ---------------------------------------------------------------

    def scenario_3(self, auto: bool) -> None:
        customer = self.customer(SCAM_CUSTOMER)
        amount = 180_000
        print(f"Scenario 3: {customer['name']} is told by a fake police officer to pay {money(amount)} to {SCAM_ACCOUNT}.")
        result = self.post("/transactions", {
            "type": "TRANSFER", "amount": amount, "sender_id": customer["customer_id"],
            "sender_balance_before": customer["balance"], "payee_id": SCAM_ACCOUNT,
            "description": f"Account {SCAM_ACCOUNT}",
        })
        txn, case_id = result["transaction"], result["case_id"]
        print(f"  Risk score {txn['probability']:.4f} (looks normal to the model) -> tier {txn['tier']} from the "
              f"{txn['tier_source'].replace('_', ' ')} -> {txn['action'].upper()}.")
        if not case_id:
            sys.exit("  Unexpected: the payment was not held. Run 'scripts/demo.py reset' and try again.")

        if not auto:
            print(f"""
  Now play the customer in the customer app (pick {customer['name']}):
    1. Open the alert "We paused a payment for a quick safety check".
    2. Reply:  Yes, it was me. I made this payment.
    3. Reply:  A police officer called me on video. He sent me this message.
       and attach the screenshot:
       {SCREENSHOT}
    4. The safety-pause screen appears. The analyst console shows case {case_id} with the scam signals.""")
            return

        self.post(f"/cases/{case_id}/chat/start")
        print('  Customer: "Yes, it was me. I made this payment."')
        turn = self.post(f"/cases/{case_id}/chat/messages", {"text": "Yes, it was me. I made this payment."})
        print(f"  Assistant: {turn['chat']['messages'][-1]['text']}")
        print(f"  Payment is still {turn['payment_status']}: a 'yes' is not the end of the check.")

        print('  Customer: "A police officer called me on video. He sent me this message." [digital arrest screenshot]')
        turn = self.post(f"/cases/{case_id}/chat/messages", {
            "text": "A police officer called me on video. He sent me this message.",
            "image_base64": base64.b64encode(SCREENSHOT.read_bytes()).decode(),
            "image_mime_type": "image/png",
        })
        for signal in turn["scam_signals"]:
            print(f"    signal: {signal['type']} ({signal['confidence']:.2f}) - {signal['evidence'][:70]}")
        print(f"  Rule engine: payment is now {turn['payment_status'].upper()} until {turn['held_until']}.")
        print(f"  Open the customer app to see the warning screen, and the analyst console for case {case_id}.")


def main() -> None:
    parser = argparse.ArgumentParser(description="ScamShield demo scenarios", epilog=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default=os.getenv("SCAMSHIELD_API", "http://localhost:8080"), help="backend base URL")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("reset", help="delete all data and reseed the demo customers")
    scenario = commands.add_parser("scenario", help="set up scenario 1, 2 or 3")
    scenario.add_argument("number", type=int, choices=[1, 2, 3])
    scenario.add_argument("--auto", action="store_true", help="scenario 3: the script plays the customer's side of the chat")
    args = parser.parse_args()

    demo = Demo(args.api)
    try:
        if args.command == "reset":
            demo.reset()
        elif args.number == 1:
            demo.scenario_1()
        elif args.number == 2:
            demo.scenario_2()
        else:
            demo.scenario_3(args.auto)
    except httpx.ConnectError:
        sys.exit(f"Cannot reach the backend at {args.api}. Is it running?")


if __name__ == "__main__":
    main()
