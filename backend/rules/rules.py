"""Rule engine: the only place that decides what happens to the money.

The ML model gives a risk score and Gemini gives evidence and scam signals,
but neither blocks or releases a payment. These rules turn their outputs into
an action, so every money decision is deterministic and auditable.
"""

import os
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone

TIERS = ["Low", "Medium", "High", "Critical"]

# A scam signal at or above this confidence triggers the safety pause...
SCAM_CONFIDENCE_THRESHOLD = 0.7
# ...and so do several different, moderately confident signals together.
SCAM_MODERATE_CONFIDENCE = 0.5
SCAM_MODERATE_COUNT = 2

# Behaviour rule: a first transfer to a new payee that is at least this many
# times the customer's typical maximum is raised to High, whatever the model
# says. The model only knows PaySim patterns; this catches the classic scam
# shape (a large payment to a stranger). It relies on the customer profile.
NEW_PAYEE_AMOUNT_MULTIPLE = 3.0
BEHAVIOUR_RULE_TYPES = ["TRANSFER"]

# Cooling-off period for the safety pause. A real bank would use hours (for
# example 24h); the default here is short so the demo can show the full cycle.
DEFAULT_SAFETY_PAUSE_SECONDS = 120


@dataclass(frozen=True)
class Decision:
    """What the bank does with a payment."""

    tier: str
    action: str           # allow | verify | hold | hold_and_escalate | safety_pause
    payment_status: str   # allowed | pending_verification | held | safety_paused
    create_case: bool
    start_chat: bool
    escalate: bool
    reason: str
    held_until: str | None = None  # ISO time, only set by the safety pause

    def to_dict(self) -> dict:
        return asdict(self)


# The tier/action table from the project brief.
TIER_RULES = {
    "Low": Decision(
        "Low", "allow", "allowed", create_case=False, start_chat=False, escalate=False,
        reason="Low risk: payment allowed.",
    ),
    "Medium": Decision(
        "Medium", "verify", "pending_verification", create_case=False, start_chat=False, escalate=False,
        reason="Medium risk: customer is asked to verify the payment.",
    ),
    "High": Decision(
        "High", "hold", "held", create_case=True, start_chat=True, escalate=False,
        reason="High risk: payment held, case created, customer chat started.",
    ),
    # The customer chat also starts on Critical, so the customer is asked about
    # the payment while the case waits for an analyst.
    "Critical": Decision(
        "Critical", "hold_and_escalate", "held", create_case=True, start_chat=True, escalate=True,
        reason="Critical risk: payment held, escalated to an analyst, customer chat started.",
    ),
}


def tier_for_score(score: float, thresholds: dict) -> str:
    """Maps a model risk score to a tier using the trained thresholds."""
    if score >= thresholds["critical"]:
        return "Critical"
    if score >= thresholds["high"]:
        return "High"
    if score >= thresholds["medium"]:
        return "Medium"
    return "Low"


def behaviour_rule_applies(payment_type: str, customer_context: dict | None) -> bool:
    """True for a large first transfer to a new payee by a known customer."""
    context = customer_context or {}
    return (
        payment_type in BEHAVIOUR_RULE_TYPES
        and context.get("known_customer", False)
        and context.get("is_new_payee", False)
        and context.get("amount_vs_typical_max", 0) >= NEW_PAYEE_AMOUNT_MULTIPLE
    )


def decide(
    score: float,
    thresholds: dict,
    in_model_scope: bool = True,
    payment_type: str | None = None,
    customer_context: dict | None = None,
) -> Decision:
    """Decision for a newly scored payment.

    Payment types the model was not trained on (no fraud labels in the data)
    are out of scope and treated as Low by rule. The behaviour rule can raise
    a Low or Medium payment to High; it never lowers a tier.
    """
    decision = TIER_RULES[tier_for_score(score, thresholds)] if in_model_scope else TIER_RULES["Low"]

    if decision.tier in ("Low", "Medium") and behaviour_rule_applies(payment_type, customer_context):
        multiple = customer_context["amount_vs_typical_max"]
        return replace(
            TIER_RULES["High"],
            reason=(
                f"Raised from {decision.tier} to High by the behaviour rule: first payment to a new payee "
                f"at {multiple}x the customer's typical maximum. Payment held, case created, customer chat started."
            ),
        )
    return decision


def safety_pause_seconds() -> int:
    return int(os.getenv("SAFETY_PAUSE_SECONDS", DEFAULT_SAFETY_PAUSE_SECONDS))


def safety_pause(scam_signals: list[dict], current_tier: str, now: datetime | None = None) -> Decision | None:
    """Returns a safety-pause decision if the chat found strong scam signals.

    scam_signals come from the customer protection agent: each has a type,
    evidence and a confidence between 0 and 1. The agent only reports them;
    this rule decides whether the payment is paused. Returns None if no signal
    is strong enough.
    """
    strong = [s for s in scam_signals if s.get("confidence", 0) >= SCAM_CONFIDENCE_THRESHOLD]
    if not strong:
        moderate = [s for s in scam_signals if s.get("confidence", 0) >= SCAM_MODERATE_CONFIDENCE]
        if len({s.get("type") for s in moderate}) < SCAM_MODERATE_COUNT:
            return None
        strong = moderate

    now = now or datetime.now(timezone.utc)
    held_until = now + timedelta(seconds=safety_pause_seconds())
    signal_types = ", ".join(sorted({s.get("type", "unknown") for s in strong}))
    return Decision(
        tier=current_tier,
        action="safety_pause",
        payment_status="safety_paused",
        create_case=True,
        start_chat=False,
        escalate=True,
        reason=f"Safety pause: strong scam signals in the customer conversation ({signal_types}).",
        held_until=held_until.isoformat(),
    )


# --- Analyst decisions (policy POL-7.3) -----------------------------------------
# What each button on the analyst console does to the payment, and the label
# that is stored as feedback for retraining the risk model.
ANALYST_DECISIONS = {
    "approve": {
        "payment_status": "rejected", "is_fraud": True, "false_positive": False,
        "summary": "Fraud or scam confirmed: payment stopped, the money stays in the customer's account.",
    },
    "release": {
        "payment_status": "released", "is_fraud": False, "false_positive": False,
        "summary": "Payment reviewed and judged genuine: payment sent.",
    },
    "reject": {
        "payment_status": "released", "is_fraud": False, "false_positive": True,
        "summary": "Alert rejected as a false alarm: payment sent, case closed as a false positive.",
    },
}


def analyst_decision_blocked(decision: str, case: dict, now: datetime | None = None) -> str | None:
    """Why this decision is not allowed right now, or None if it is.

    A payment can always be stopped. It cannot be sent while a safety pause
    is still running: the cooling-off period exists so that nobody, including
    a pressured customer or a hurried analyst, can rush it (POL-5.5, POL-5.6).
    """
    if case["payment_status"] not in ("held", "safety_paused"):
        return f"The payment is already {case['payment_status']}."
    sends_payment = ANALYST_DECISIONS[decision]["payment_status"] == "released"
    if sends_payment and case["payment_status"] == "safety_paused":
        now = now or datetime.now(timezone.utc)
        if now < datetime.fromisoformat(case["held_until"]):
            return f"The safety pause runs until {case['held_until']}. The payment cannot be sent before then."
    return None
