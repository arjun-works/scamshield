"""Structured output of the investigation agent (stored on the case)."""

from pydantic import BaseModel, Field


class PolicyReference(BaseModel):
    section: str  # e.g. "POL-2.10"
    title: str


class ScamSignal(BaseModel):
    """Filled in by the customer protection agent (Phase 5)."""

    type: str
    evidence: str
    confidence: float = Field(ge=0, le=1)


class InvestigationCase(BaseModel):
    """The case file written by the investigation agent.

    The facts (transaction, probability, tier) are copied from stored data by
    code. The model only writes the explanatory fields below them.
    """

    case_id: str
    transaction: dict
    probability: float
    tier: str
    tier_source: str

    top_risk_factors: list[str] = Field(min_length=1, description="Plain-English risk factors")
    historical_evidence: list[str] = Field(description="What the customer's history shows")
    payee_mule_evidence: list[str] = Field(description="What the payee's history shows")
    policy_references: list[PolicyReference] = Field(min_length=1)
    recommended_next_step: str = Field(min_length=1, description="Advice for the analyst; not an action")
    investigation_summary: str = Field(min_length=1)
    scam_signals: list[ScamSignal] = []

    model: str
    tools_called: list[str]
    generated_at: str


# JSON schema of the case file, for documentation and the frontend.
INVESTIGATION_CASE_SCHEMA = InvestigationCase.model_json_schema()
