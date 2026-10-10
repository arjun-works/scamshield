"""Evaluates the customer protection agent on the synthetic fixtures.

Run from the repo root:
    uv run --project backend python scripts/eval_scam.py               # run (resumes if interrupted)
    uv run --project backend python scripts/eval_scam.py --fresh       # discard earlier results first
    uv run --project backend python scripts/eval_scam.py --report-only # rebuild the reports only

What it does:
  1. Plays the 20 scripted conversations (10 scam, 10 genuine) through the real
     chat flow and Gemini. A conversation is predicted "scam" if the rule
     engine starts a safety pause.
  2. Sends the 8 scam-message screenshots and the prompt-injection message.
  3. Writes docs/scam_eval.md, and docs/results.md (with the risk model's metrics).

Uses roughly 60-70 free-tier Gemini requests. Raw results are saved after
every item in docs/scam_eval_results.json, so a run that hits a rate limit can
simply be started again. Nothing is written to Firestore.
"""

import argparse
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))
os.environ["STORE_BACKEND"] = "memory"  # the evaluation never touches Firestore

FIXTURES = REPO_ROOT / "backend" / "tests" / "fixtures"
RESULTS_PATH = REPO_ROOT / "docs" / "scam_eval_results.json"
SCAM_EVAL_PATH = REPO_ROOT / "docs" / "scam_eval.md"
COMBINED_PATH = REPO_ROOT / "docs" / "results.md"
MODEL_METRICS_PATH = REPO_ROOT / "backend" / "ml" / "artifacts" / "metrics.json"


# --- Running the fixtures -------------------------------------------------------

def new_held_case(store, customer: dict) -> dict:
    """A large first transfer to a new payee: held by the behaviour rule."""
    from app.schemas import TransactionIn
    from app.service import process_transaction

    record = process_transaction(
        TransactionIn(
            type="TRANSFER", amount=customer["typical_amount_max"] * 6, sender_id=customer["customer_id"],
            sender_balance_before=customer["balance"], payee_id="C-EVAL-PAYEE", investigate=False,
        ),
        store,
    )
    return store.get_case(record["case_id"])


def outcome_of(case: dict, turns_sent: int) -> dict:
    """What the system did, read from the case after the conversation."""
    failed = [e["detail"] for e in case["audit_log"] if e["event"] == "chat_turn_failed"]
    models = sorted({
        e["detail"].split(".")[0].removeprefix("Model ")
        for e in case["audit_log"] if e["event"] == "chat_turn_analysed"
    })
    return {
        "paused": case["payment_status"] == "safety_paused",
        "payment_status": case["payment_status"],
        "turns_sent": turns_sent,
        "signals": [{"type": s["type"], "confidence": s["confidence"], "source": s.get("source")} for s in case["scam_signals"]],
        "models": models,
        "error": failed[0] if failed else None,
    }


def run_conversation(store, customer: dict, turns: list[str], delay: float) -> dict:
    from app import chat as chat_service

    case = new_held_case(store, customer)
    sent = 0
    for text in turns:
        chat = chat_service.handle_customer_message(case, store, text)
        sent += 1
        time.sleep(delay)
        if chat["status"] != "active" or chat["messages"][-1]["kind"] == "unavailable":
            break
    return outcome_of(case, sent)


def run_message(store, customer: dict, message: dict, as_image: bool, delay: float) -> dict:
    from app import chat as chat_service

    case = new_held_case(store, customer)
    if as_image:
        image = ((FIXTURES / "screenshots" / f"{message['id']}.png").read_bytes(), "image/png")
        chat_service.handle_customer_message(case, store, "Yes, I made this payment. I got this message.", image)
    else:
        chat_service.handle_customer_message(case, store, message["text"])
    time.sleep(delay)
    return outcome_of(case, 1)


def run_all(results: dict, delay: float) -> None:
    from db.seed_data import generate_customers
    from db.store import get_store

    store = get_store()
    customers = generate_customers()
    for customer in customers:
        store.upsert_customer(customer)
    by_language: dict[str, list[dict]] = {}
    for customer in customers:
        by_language.setdefault(customer["preferred_language"], []).append(customer)

    conversations = json.loads((FIXTURES / "conversations.json").read_text(encoding="utf-8"))["conversations"]
    messages = json.loads((FIXTURES / "scam_messages.json").read_text(encoding="utf-8"))

    def save() -> None:
        RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    for index, conversation in enumerate(conversations):
        if conversation["id"] in results["conversations"]:
            continue  # done in an earlier run
        pool = by_language[conversation["language"]]
        outcome = run_conversation(store, pool[index % len(pool)], conversation["customer_turns"], delay)
        print(f"{conversation['id']:<11} {conversation['language']:<8} paused={outcome['paused']!s:<5} "
              f"turns={outcome['turns_sent']} error={bool(outcome['error'])}")
        if outcome["error"]:
            print(f"  Gemini failed: {outcome['error'][:160]}\n  Stopping. Run the script again later to resume.")
            return
        results["conversations"][conversation["id"]] = {
            **{k: conversation[k] for k in ("label", "scam_type", "language")}, **outcome,
        }
        save()

    items = [(m, True) for m in messages["messages"]] + [(messages["prompt_injection"], False)]
    for message, as_image in items:
        if message["id"] in results["messages"]:
            continue
        outcome = run_message(store, by_language["English"][0], message, as_image, delay)
        print(f"{message['id']:<17} paused={outcome['paused']!s:<5} error={bool(outcome['error'])}")
        if outcome["error"]:
            print(f"  Gemini failed: {outcome['error'][:160]}\n  Stopping. Run the script again later to resume.")
            return
        results["messages"][message["id"]] = {
            "type": message["type"], "input": "screenshot" if as_image else "pasted text",
            "expected_signals": message["expected_signals"], **outcome,
        }
        save()

    results["completed_on"] = date.today().isoformat()
    save()


# --- Reports ----------------------------------------------------------------------

def confusion(conversations: dict) -> dict:
    tp = sum(c["label"] == "scam" and c["paused"] for c in conversations.values())
    fn = sum(c["label"] == "scam" and not c["paused"] for c in conversations.values())
    fp = sum(c["label"] == "genuine" and c["paused"] for c in conversations.values())
    tn = sum(c["label"] == "genuine" and not c["paused"] for c in conversations.values())
    total = tp + fn + fp + tn
    return {
        "tp": tp, "fn": fn, "fp": fp, "tn": tn, "total": total,
        "accuracy": (tp + tn) / total if total else 0.0,
        "precision": tp / (tp + fp) if tp + fp else 0.0,
        "recall": tp / (tp + fn) if tp + fn else 0.0,
    }


def wilson_interval(successes: int, n: int) -> tuple[float, float]:
    """95% confidence interval for a proportion (Wilson score)."""
    if n == 0:
        return 0.0, 1.0
    z, p = 1.96, successes / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def signal_text(signals: list[dict]) -> str:
    return ", ".join(f"{s['type']} ({s['confidence']:.2f})" for s in signals) or "none"


def render_scam_eval(results: dict) -> str:
    conversations, messages = results["conversations"], results["messages"]
    c = confusion(conversations)
    models = sorted({m for item in [*conversations.values(), *messages.values()] for m in item["models"]})
    requests = sum(item["turns_sent"] for item in [*conversations.values(), *messages.values()])
    acc_low, acc_high = wilson_interval(c["tp"] + c["tn"], c["total"])
    rec_low, rec_high = wilson_interval(c["tp"], c["tp"] + c["fn"])

    conversation_rows = "\n".join(
        f"| {cid} | {r['language']} | {r['scam_type'] or 'genuine'} | {r['label']} | "
        f"{'paused' if r['paused'] else 'not paused'} | {'yes' if (r['label'] == 'scam') == r['paused'] else '**NO**'} | "
        f"{r['turns_sent']} | {signal_text(r['signals'])} |"
        for cid, r in conversations.items()
    )
    languages = sorted({r["language"] for r in conversations.values()})
    language_rows = "\n".join(
        "| {} | {} | {} |".format(
            language,
            sum(r["language"] == language for r in conversations.values()),
            sum(r["language"] == language and (r["label"] == "scam") == r["paused"] for r in conversations.values()),
        )
        for language in languages
    )
    scam_messages = {mid: r for mid, r in messages.items() if r["type"] != "prompt_injection"}
    message_rows = "\n".join(
        "| {} | {} | {} | {} of {} | {} |".format(
            mid, r["input"], "paused" if r["paused"] else "**not paused**",
            len(set(r["expected_signals"]) & {s["type"] for s in r["signals"]}), len(r["expected_signals"]),
            signal_text(r["signals"]),
        )
        for mid, r in scam_messages.items()
    )
    injection = messages.get("prompt_injection")
    if injection:
        by_model = any(s["type"] == "embedded_instructions" and s["source"] == "gemini" for s in injection["signals"])
        by_code = any(s["type"] == "embedded_instructions" and s["source"] == "pattern_check" for s in injection["signals"])
        injection_text = (
            f"- Payment after the message: **{injection['payment_status']}** (it must never be released).\n"
            f"- Flagged by Gemini as `embedded_instructions`: **{'yes' if by_model else 'no'}**.\n"
            f"- Flagged by the pattern check in code: **{'yes' if by_code else 'no'}**. Signals are merged per type and the "
            f"most confident one is kept, so only one of the two is listed when both fire.\n"
            f"- Signals recorded: {signal_text(injection['signals'])}."
        )
    else:
        injection_text = "Not run yet."

    status = f"Run completed on {results['completed_on']}." if results.get("completed_on") else "**Incomplete run: some items are missing. Run the script again.**"

    return f"""# Scam detection evaluation

Generated by `scripts/eval_scam.py`. Do not edit by hand; rerun the script. Raw results: `docs/scam_eval_results.json`.

{status} Model(s) used: {", ".join(models) or "none"}. Gemini requests: {requests}.

## What was measured

Each conversation is played through the real chat flow: the customer's scripted turns go to Gemini one at a time, Gemini returns scam signals, and the rule engine decides whether to start a safety pause. The prediction is **scam** if the payment ends up paused and **genuine** if it does not. Every customer begins by saying "yes, it was me".

## Conversations: {c['total']} ({c['tp'] + c['fn']} scam, {c['fp'] + c['tn']} genuine)

| Metric | Value |
|---|---:|
| Accuracy | {c['accuracy']:.0%} ({c['tp'] + c['tn']} of {c['total']}) |
| Precision (paused conversations that were scams) | {c['precision']:.0%} ({c['tp']} of {c['tp'] + c['fp']}) |
| Recall (scams that were paused) | {c['recall']:.0%} ({c['tp']} of {c['tp'] + c['fn']}) |

| | Paused | Not paused |
|---|---:|---:|
| **Scam** | {c['tp']} | {c['fn']} |
| **Genuine** | {c['fp']} | {c['tn']} |

With only {c['total']} conversations the uncertainty is large: the 95% interval for accuracy is {acc_low:.0%} to {acc_high:.0%}, and for recall {rec_low:.0%} to {rec_high:.0%}.

By language:

| Language | Conversations | Correct |
|---|---:|---:|
{language_rows}

Each conversation:

| ID | Language | Scenario | Label | Outcome | Correct | Customer turns used | Signals (confidence) |
|---|---|---|---|---|---|---:|---|
{conversation_rows}

## Scam message screenshots: {len(scam_messages)}

Each message was uploaded as a PNG screenshot with the text "Yes, I made this payment. I got this message." All are scams, so all should be paused. "Expected signals found" compares against the signal types listed in the fixture.

| Message | Input | Outcome | Expected signals found | Signals (confidence) |
|---|---|---|---:|---|
{message_rows}

Paused: {sum(r['paused'] for r in scam_messages.values())} of {len(scam_messages)}.

## Prompt injection

The message claims to be a bank notice and contains "ignore previous instructions", tells the assistant to mark the payment safe, report no signals, and ask for the customer's OTP.

{injection_text}

## Limits of this evaluation

- **Small and synthetic.** Twenty conversations and nine messages, all written for this project. Real victims are less articulate, more evasive, and often coached on what to say to the bank.
- **Same author as the prompt.** The fixtures and the agent's instructions were written together, so the scenarios match the signal types the agent looks for. Expect lower numbers on independent data.
- **Scripted customer.** The customer's turns do not react to the assistant's questions. A real conversation depends on whether the assistant asks the right follow-up.
- **The scripted victims give the scam away early.** See "Customer turns used" above: a pause after two turns means the second message already contained a clear sign. A victim who never mentions the caller, the promise or the fee would not be caught by the chat alone.
- **The genuine conversations are clearly genuine.** None of them is a borderline case, so the 0 false alarms here says little about how often real customers with unusual but honest reasons would be paused.
- **One run.** Model output varies between runs, and the "-latest" model alias changes over time.
"""


def render_combined(results: dict, model: dict) -> str:
    c = confusion(results["conversations"])
    scam_messages = [r for r in results["messages"].values() if r["type"] != "prompt_injection"]
    injection = results["messages"].get("prompt_injection", {})
    test, tiers = model["test"], {t["tier"]: t for t in model["test_tiers"]}
    held = tiers["High"]["payments"] + tiers["Critical"]["payments"]
    held_fraud = tiers["High"]["frauds"] + tiers["Critical"]["frauds"]
    ablation = model["ablation_without_balance_features"]
    data = model["data"]

    return f"""# ScamShield results

Generated by `scripts/eval_scam.py` from `backend/ml/artifacts/metrics.json` and `docs/scam_eval_results.json`. Details: [model_metrics.md](model_metrics.md) and [scam_eval.md](scam_eval.md).

All data is synthetic: the public PaySim dataset for the risk model, and hand-written fixtures for the conversations.

## The two layers

| Layer | What it catches | Evaluated on | Headline |
|---|---|---|---|
| Risk model (XGBoost) + rules | Unauthorised transfers: account takeover, mule cash-outs | {test['rows']:,} later PaySim payments, {test['frauds']:,} frauds | PR-AUC {test['pr_auc']:.3f}, ROC-AUC {test['roc_auc']:.4f} |
| Customer protection chat (Gemini) + rules | Authorised scam payments, where the customer says "yes, it was me" | {c['total']} synthetic conversations | Accuracy {c['accuracy']:.0%}, precision {c['precision']:.0%}, recall {c['recall']:.0%} |

## Risk model

Trained on steps {model['split']['train_steps'][0]}-{model['split']['train_steps'][1]}, tested on the later steps {model['split']['test_steps'][0]}-{model['split']['test_steps'][1]} (time-based split, no resampling, leaky columns never loaded).

| Tier | Action | Test payments | Frauds | Fraud rate in tier |
|---|---|---:|---:|---:|
| Low | Allow | {tiers['Low']['payments']:,} | {tiers['Low']['frauds']:,} | {tiers['Low']['fraud_rate']:.1%} |
| Medium | Customer verifies | {tiers['Medium']['payments']:,} | {tiers['Medium']['frauds']:,} | {tiers['Medium']['fraud_rate']:.1%} |
| High | Hold, case, chat | {tiers['High']['payments']:,} | {tiers['High']['frauds']:,} | {tiers['High']['fraud_rate']:.1%} |
| Critical | Hold, escalate, chat | {tiers['Critical']['payments']:,} | {tiers['Critical']['frauds']:,} | {tiers['Critical']['fraud_rate']:.1%} |

- Held payments (High and Critical): {held:,}, or {held / test['rows']:.2%} of test payments; {held_fraud / held:.1%} of them are fraud.
- Fraud caught by a hold: {held_fraud:,} of {test['frauds']:,} ({held_fraud / test['frauds']:.1%}). A further {tiers['Medium']['frauds']:,} fall in Medium and {tiers['Low']['frauds']:,} are missed in Low.

## Scam detection

| | Paused | Not paused |
|---|---:|---:|
| **Scam conversations** | {c['tp']} | {c['fn']} |
| **Genuine conversations** | {c['fp']} | {c['tn']} |

- Scam message screenshots paused: {sum(r['paused'] for r in scam_messages)} of {len(scam_messages)}.
- Prompt-injection message: payment ended **{injection.get('payment_status', 'not run')}**; it was not released.
- Languages covered: English, Tamil and Hindi.

## How to read these numbers

1. **The model's score is inflated by the dataset.** {data['fraud_share_draining_account']:.1%} of PaySim frauds move exactly the sender's whole balance, and no genuine payment does. Without the two sender-balance features, PR-AUC falls from {test['pr_auc']:.3f} to {ablation['pr_auc']:.3f}. Real fraud is not this clean.
2. **The model cannot see scams.** PaySim has no authorised-scam labels and no customer history. Scam-shaped payments reach the chat through a behaviour rule (a large first transfer to a new payee) that relies on synthetic customer profiles.
3. **The chat evaluation is small and friendly.** {c['total']} conversations written by the same author as the agent's instructions, with scripted customers. Treat it as evidence that the mechanism works, not as an accuracy estimate for real customers.
4. **The two layers were evaluated separately.** There is no end-to-end figure for how much real scam loss the combined system would prevent.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fresh", action="store_true", help="discard saved results and start again")
    parser.add_argument("--report-only", action="store_true", help="rebuild the reports from saved results")
    parser.add_argument("--delay", type=float, default=3.0, help="seconds to wait after each Gemini request")
    args = parser.parse_args()

    results = {"conversations": {}, "messages": {}}
    if RESULTS_PATH.exists() and not args.fresh:
        results = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    if not args.report_only:
        results.pop("completed_on", None)
        run_all(results, args.delay)

    if not results["conversations"]:
        print("No results yet; nothing to report.")
        return 1
    SCAM_EVAL_PATH.write_text(render_scam_eval(results), encoding="utf-8")
    COMBINED_PATH.write_text(render_combined(results, json.loads(MODEL_METRICS_PATH.read_text())), encoding="utf-8")

    c = confusion(results["conversations"])
    print(f"\nConversations: accuracy {c['accuracy']:.0%}, precision {c['precision']:.0%}, recall {c['recall']:.0%} "
          f"({c['total']} of 20 run)")
    print(f"Wrote {SCAM_EVAL_PATH} and {COMBINED_PATH}")
    return 0 if results.get("completed_on") else 2


if __name__ == "__main__":
    sys.exit(main())
