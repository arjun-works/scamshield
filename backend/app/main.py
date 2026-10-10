"""ScamShield API entry point.

Run locally from the backend/ folder:
    uv run uvicorn app.main:app --reload --port 8080

Interactive docs: http://localhost:8080/docs
"""

import base64
import binascii
import secrets
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app import config
from app import chat as chat_service
from app.schemas import (
    ChatMessageIn, DecisionIn, ScoreResult, TransactionIn, TransactionOut, VerifyIn, current_step,
)
from app.scoring import get_model, resolve_payee_stats, score_transaction
from app.service import (
    apply_analyst_decision, build_customer_context, cancel_payment, process_transaction, verify_payment,
)
from agents.investigation import investigate_case
from db.seed_data import seed_store
from db.store import get_store

@asynccontextmanager
async def lifespan(_: FastAPI):
    """Load the model and the stored data before serving, so the first
    request is not slow and a bad Firestore setup fails at startup."""
    get_model()
    get_store()
    yield


app = FastAPI(title="ScamShield API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    """Liveness check used by Cloud Run and the frontend."""
    return {"status": "ok", "service": "scamshield"}


@app.post("/score", response_model=ScoreResult)
def score(txn: TransactionIn, store=Depends(get_store)) -> dict:
    """Scores a payment without saving anything (a what-if check)."""
    return score_transaction(txn, resolve_payee_stats(txn, store), build_customer_context(txn, store))


@app.post("/transactions", response_model=TransactionOut)
def submit_transaction(txn: TransactionIn, background: BackgroundTasks, store=Depends(get_store)) -> dict:
    """Scores a payment, applies the rules, saves it, and opens a case if held.

    For a held payment the Gemini investigation runs in the background after
    the response is sent; poll GET /cases/{id} for the result.
    """
    if store.get_transaction(txn.transaction_id):
        raise HTTPException(status_code=409, detail="Transaction already exists")
    auto_investigate = config.AUTO_INVESTIGATE and txn.investigate
    record = process_transaction(txn, store, queue_investigation=auto_investigate)
    if record["case_id"] and auto_investigate:
        background.add_task(investigate_case, record["case_id"])
    return {"transaction": record, "case_id": record["case_id"]}


@app.get("/transactions")
def list_transactions(limit: int = 50, sender_id: str | None = None, store=Depends(get_store)) -> list[dict]:
    """Recent transactions, newest first. Polled by both frontends."""
    return store.list_transactions(limit=limit, sender_id=sender_id)


@app.get("/customers")
def list_customers(store=Depends(get_store)) -> list[dict]:
    """Demo customers (synthetic profiles)."""
    return store.list_customers()


@app.get("/customers/{customer_id}")
def get_customer(customer_id: str, limit: int = 20, store=Depends(get_store)) -> dict:
    """A customer's profile with their recent transactions."""
    customer = store.get_customer(customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return {"customer": customer, "transactions": store.list_transactions(limit=limit, sender_id=customer_id)}


@app.get("/cases")
def list_cases(status: str | None = None, tier: str | None = None, limit: int = 50, store=Depends(get_store)) -> list[dict]:
    """Cases, newest first, optionally filtered by status or tier."""
    return store.list_cases(status=status, tier=tier, limit=limit)


@app.get("/cases/{case_id}")
def get_case(case_id: str, store=Depends(get_store)) -> dict:
    case = store.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


@app.post("/cases/{case_id}/investigate")
def start_investigation(case_id: str, background: BackgroundTasks, force: bool = False, store=Depends(get_store)) -> dict:
    """Starts the Gemini investigation for a case (an analyst action).

    A finished investigation is stored on the case and returned as is, so
    Gemini is not called twice for the same case. Use force=true to redo it.
    """
    case = store.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    already_done = case.get("investigation") and not force
    in_progress = case["investigation_status"] in ("queued", "running")
    if not already_done and not in_progress:
        case["investigation_status"] = "queued"
        store.save_case(case)
        background.add_task(investigate_case, case_id, force)
    return case


def _case_or_404(case_id: str, store) -> dict:
    case = store.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


@app.post("/cases/{case_id}/chat/start")
def start_chat(case_id: str, store=Depends(get_store)) -> dict:
    """Opens the customer verification chat (no Gemini call). Safe to call twice."""
    return chat_service.start_chat(_case_or_404(case_id, store), store)


@app.get("/cases/{case_id}/chat")
def get_chat(case_id: str, store=Depends(get_store)) -> dict:
    """The chat transcript. Polled by the customer app and the analyst console."""
    _case_or_404(case_id, store)
    chat = store.get_chat(case_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not started")
    return chat


@app.post("/cases/{case_id}/chat/messages")
def send_chat_message(case_id: str, message: ChatMessageIn, store=Depends(get_store)) -> dict:
    """A customer message, optionally with a screenshot. One Gemini request.

    Returns the updated chat and the case's payment status, so the customer
    app can show the safety-pause screen straight away.
    """
    case = _case_or_404(case_id, store)
    image = None
    if message.image_base64:
        if message.image_mime_type not in chat_service.IMAGE_TYPES:
            raise HTTPException(status_code=422, detail=f"Image type must be one of {chat_service.IMAGE_TYPES}")
        try:
            data = base64.b64decode(message.image_base64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(status_code=422, detail="image_base64 is not valid base64") from None
        if len(data) > chat_service.MAX_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="Image is larger than 5 MB")
        image = (data, message.image_mime_type)
    if not message.text.strip() and image is None:
        raise HTTPException(status_code=422, detail="Send some text, an image, or both")

    chat = chat_service.handle_customer_message(case, store, message.text.strip(), image)
    return {
        "chat": chat,
        "payment_status": case["payment_status"],
        "held_until": case.get("held_until"),
        "scam_signals": case["scam_signals"],
    }


@app.post("/cases/{case_id}/cancel")
def cancel_case_payment(case_id: str, store=Depends(get_store)) -> dict:
    """The customer cancels their held or paused payment (always allowed)."""
    try:
        return cancel_payment(_case_or_404(case_id, store), store)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@app.post("/transactions/{transaction_id}/verify")
def verify_transaction(transaction_id: str, answer: VerifyIn, store=Depends(get_store)) -> dict:
    """The customer confirms or denies a Medium-tier payment."""
    transaction = store.get_transaction(transaction_id)
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    try:
        return verify_payment(transaction, answer.confirmed, store)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@app.post("/cases/{case_id}/decision")
def decide_case(case_id: str, body: DecisionIn, store=Depends(get_store)) -> dict:
    """An analyst's Approve / Reject / Release decision. Writes a feedback record."""
    case = _case_or_404(case_id, store)
    try:
        feedback = apply_analyst_decision(case, body.decision, body.reason.strip(), body.analyst, store)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return {"case": case, "feedback": feedback}


@app.get("/feedback")
def list_feedback(limit: int = 200, store=Depends(get_store)) -> list[dict]:
    """Analyst decisions stored as labelled examples for retraining."""
    return store.list_feedback(limit=limit)


@app.post("/admin/reset")
def reset_demo_data(x_admin_token: str | None = Header(default=None), store=Depends(get_store)) -> dict:
    """Deletes all ScamShield data and reseeds the synthetic demo customers.

    Used by scripts/demo.py before a demo. Needs the X-Admin-Token header to
    match ADMIN_TOKEN; if ADMIN_TOKEN is not configured the endpoint is off.
    """
    if not config.ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Reset is disabled: ADMIN_TOKEN is not configured")
    if not secrets.compare_digest(x_admin_token or "", config.ADMIN_TOKEN):
        raise HTTPException(status_code=401, detail="Wrong or missing X-Admin-Token")
    store.wipe()
    return seed_store(store, now_step=current_step())
