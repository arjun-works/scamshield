"""Request and response shapes for the API."""

import time
import uuid
from typing import Literal

from pydantic import BaseModel, Field

IST_OFFSET_SECONDS = 5 * 3600 + 1800


def current_step() -> int:
    """Hour counter for live payments (PaySim's 'step' is also one hour).

    Hours since the epoch in India time, so step % 24 is the local hour.
    """
    return int((time.time() + IST_OFFSET_SECONDS) // 3600)


class TransactionIn(BaseModel):
    """A payment to score. Field names are plain; PaySim names are in comments."""

    transaction_id: str = Field(default_factory=lambda: f"TXN-{uuid.uuid4().hex[:10].upper()}")
    step: int = Field(default_factory=current_step, ge=0, description="Hour counter (PaySim step)")
    type: Literal["TRANSFER", "CASH_OUT", "PAYMENT", "CASH_IN", "DEBIT"]
    amount: float = Field(gt=0)
    sender_id: str                                           # nameOrig
    sender_balance_before: float = Field(ge=0)               # oldbalanceOrg
    payee_id: str                                            # nameDest
    payee_balance_before: float = Field(default=0.0, ge=0)   # oldbalanceDest
    description: str | None = None                           # e.g. "Rent"
    # Set to false to skip the automatic Gemini investigation (the simulator
    # does this to save free-tier quota; an analyst can still start one).
    investigate: bool = True

    # Payee history. Normally left empty and filled in from stored
    # transactions; the simulator can pass the dataset's values instead.
    payee_distinct_senders_before: int | None = Field(default=None, ge=0)
    payee_inflow_count_24h: int | None = Field(default=None, ge=0)
    payee_inflow_amount_24h: float | None = Field(default=None, ge=0)


class RiskFactor(BaseModel):
    feature: str
    label: str
    value: float
    shap_value: float
    direction: str
    text: str


class ScoreResult(BaseModel):
    transaction_id: str
    probability: float      # model risk score, 0 to 1 (not a calibrated probability)
    tier: str               # Low | Medium | High | Critical
    tier_source: str        # model | behaviour_rule
    action: str             # allow | verify | hold | hold_and_escalate
    payment_status: str     # allowed | pending_verification | held
    reason: str
    in_model_scope: bool
    risk_factors: list[RiskFactor]
    payee_stats: dict
    model_trained_on: str


class ChatMessageIn(BaseModel):
    """A customer message: text, a screenshot, or both."""

    text: str = Field(default="", max_length=4000)
    image_base64: str | None = None       # screenshot of an SMS/WhatsApp message
    image_mime_type: str | None = None    # image/png, image/jpeg or image/webp


class VerifyIn(BaseModel):
    confirmed: bool  # true = "yes, I made this payment"


class DecisionIn(BaseModel):
    """An analyst's decision on a case."""

    decision: Literal["approve", "reject", "release"]
    reason: str = Field(min_length=3, max_length=1000)
    analyst: str = Field(default="analyst-demo", max_length=80)


class TransactionOut(BaseModel):
    transaction: dict
    case_id: str | None = None
