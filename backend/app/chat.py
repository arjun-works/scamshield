"""The customer verification chat for a held payment.

Flow for each customer message:
  1. store the message (and check it for embedded instructions),
  2. Gemini replies and reports scam signals (agents/protection.py),
  3. signals are merged into the case and logged for audit,
  4. the rule engine decides whether to start a safety pause.

Gemini's part is steps 2 only. If it is unavailable, the payment simply stays
on hold and the customer is told so.
"""

from agents import protection
from agents.messages import (
    ASSISTANT_UNAVAILABLE, CHAT_CLOSED, OPENING, PAYMENT_DENIED, SAFETY_WARNING,
    indian_amount, language_of, signal_list,
)
from db.store import now_iso
from rules.rules import safety_pause

# Limits that bound Gemini usage and request size.
MAX_CUSTOMER_TURNS = 8
MAX_TEXT_LENGTH = 4000
MAX_IMAGE_BYTES = 5 * 1024 * 1024
IMAGE_TYPES = ["image/png", "image/jpeg", "image/webp"]


def _audit(case: dict, actor: str, event: str, detail: str) -> None:
    case["audit_log"].append({"at": now_iso(), "actor": actor, "event": event, "detail": detail})


def _say(chat: dict, text: str, kind: str = "reply") -> None:
    chat["messages"].append({"role": "assistant", "kind": kind, "text": text, "at": now_iso()})


def start_chat(case: dict, store) -> dict:
    """Opens the chat with a fixed greeting in the customer's language. Idempotent."""
    chat = store.get_chat(case["case_id"])
    if chat is not None:
        return chat

    customer = store.get_customer(case["sender_id"])
    language = language_of(customer)
    context = case.get("customer_context") or {}
    chat = {
        "case_id": case["case_id"],
        "customer_id": case["sender_id"],
        "language": language,
        "status": "active",  # active | safety_paused | closed
        "created_at": now_iso(),
        "messages": [],
    }
    _say(chat, OPENING[language].format(
        name=(customer or {}).get("name", "there"),
        amount=indian_amount(case["amount"]),
        payee=context.get("payee_name") or case["payee_id"],
    ), kind="opening")
    _audit(case, "protection_agent", "chat_started", f"Verification chat opened in {language}.")
    store.save_chat(chat)
    store.save_case(case)
    return chat


def merge_signals(existing: list[dict], new: list[dict]) -> list[dict]:
    """One entry per signal type, keeping the most confident evidence."""
    merged = {s["type"]: s for s in existing}
    for signal in new:
        current = merged.get(signal["type"])
        if current is None or signal["confidence"] >= current["confidence"]:
            merged[signal["type"]] = signal
    return sorted(merged.values(), key=lambda s: s["confidence"], reverse=True)


def handle_customer_message(case: dict, store, text: str = "", image: tuple[bytes, str] | None = None) -> dict:
    """Processes one customer message and returns the updated chat."""
    chat = start_chat(case, store)
    language = chat["language"]
    chat["messages"].append({
        "role": "customer",
        "kind": "image" if image else "text",
        "text": text,
        "has_image": image is not None,
        "at": now_iso(),
    })
    customer_message = chat["messages"][-1]

    # Once paused or closed, no more Gemini calls: the fraud team takes over.
    customer_turns = sum(m["role"] == "customer" for m in chat["messages"])
    if chat["status"] != "active" or customer_turns > MAX_CUSTOMER_TURNS:
        if chat["status"] == "active":
            chat["status"] = "closed"
        _say(chat, CHAT_CLOSED[language], kind="closed")
        store.save_chat(chat)
        return chat

    # Checked in code, independently of the model.
    new_signals = []
    injected = protection.detect_embedded_instructions(text)
    if injected:
        new_signals.append(injected)

    analysis = None
    try:
        analysis, model_name = protection.analyse_turn(case, chat["messages"], language, image)
    except Exception as exc:
        _audit(case, "protection_agent", "chat_turn_failed", str(exc)[:300])
        _say(chat, ASSISTANT_UNAVAILABLE[language], kind="unavailable")

    if analysis is not None:
        customer_message["evidence_transcript"] = analysis.evidence_transcript
        # The transcript of a screenshot is untrusted text too.
        injected_in_image = protection.detect_embedded_instructions(analysis.evidence_transcript)
        if injected_in_image:
            new_signals.append(injected_in_image)
        new_signals.extend({**s.model_dump(), "source": "gemini"} for s in analysis.scam_signals)
        found = ", ".join(f"{s.type} ({s.confidence:.2f})" for s in analysis.scam_signals) or "none"
        _audit(
            case, "protection_agent", "chat_turn_analysed",
            f"Model {model_name}. Customer response: {analysis.customer_response}. Signals: {found}.",
        )
        _say(chat, analysis.reply)

    if new_signals:
        case["scam_signals"] = merge_signals(case["scam_signals"], new_signals)
        if case.get("investigation"):
            case["investigation"]["scam_signals"] = [
                {k: s[k] for k in ("type", "evidence", "confidence")} for s in case["scam_signals"]
            ]

    # The rule engine, not Gemini, decides on the safety pause.
    pause = safety_pause(case["scam_signals"], current_tier=case["tier"])
    if pause is not None:
        case.update({
            "action": pause.action,
            "payment_status": pause.payment_status,
            "held_until": pause.held_until,
            "status": "escalated",
        })
        _audit(case, "rule_engine", "safety_pause", f"{pause.reason} Held until {pause.held_until}.")
        chat["status"] = "safety_paused"
        strong = [s for s in case["scam_signals"] if s["confidence"] >= 0.5]
        _say(chat, SAFETY_WARNING[language].format(signals=signal_list(strong, language)), kind="safety_warning")
        _update_transaction(case, store)
    elif analysis is not None and analysis.customer_response == "denies":
        # The customer did not make the payment: possible account takeover.
        case["status"] = "escalated"
        case["customer_denied_payment"] = True
        _audit(case, "rule_engine", "escalated", "Customer says they did not make this payment. Payment stays held.")
        chat["status"] = "closed"
        _say(chat, PAYMENT_DENIED[language], kind="closed")
    elif analysis is not None and analysis.enough_information and analysis.customer_response == "confirms":
        # Nothing suspicious found. The payment still waits for an analyst.
        if not case.get("chat_outcome"):
            case["chat_outcome"] = "no_strong_scam_signals"
            _audit(case, "protection_agent", "chat_completed", "Customer confirmed the payment; no strong scam signals. Awaiting analyst decision.")

    store.save_chat(chat)
    store.save_case(case)
    return chat


def _update_transaction(case: dict, store) -> None:
    """Copies the case's payment status onto the transaction record."""
    transaction = store.get_transaction(case["transaction_id"])
    if transaction is not None:
        transaction.update({
            "payment_status": case["payment_status"],
            "action": case["action"],
            "held_until": case.get("held_until"),
        })
        store.add_transaction(transaction)
