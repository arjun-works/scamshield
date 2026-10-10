"""Data stores used by the API.

InMemoryStore keeps everything in process memory (tests, quick local runs).

FirestoreStore adds persistence: every write also goes to Firestore, and the
data is loaded back into memory when the server starts. All reads are served
from memory. That keeps the polling frontends from using up the Firestore
free-tier read quota (50,000 reads a day), at the price of assuming a single
backend instance. See the scale-up notes in the README for the alternative.
"""

import uuid
from datetime import datetime, timezone

from ml.features import INFLOW_TYPES, PAYEE_WINDOW_STEPS

COLLECTIONS = ["customers", "transactions", "cases", "chats", "feedback"]

# Payment statuses that mean the money reached the payee.
COMPLETED_STATUSES = ("allowed", "released")

# How much is loaded back from Firestore on startup (newest first).
MAX_TRANSACTIONS_LOADED = 1000
MAX_CASES_LOADED = 500


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class InMemoryStore:
    """Keeps customers, transactions and cases in process memory."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """Clears memory only."""
        self._customers: dict[str, dict] = {}
        self._transactions: dict[str, dict] = {}
        self._cases: dict[str, dict] = {}
        self._chats: dict[str, dict] = {}
        self._feedback: dict[str, dict] = {}

    def wipe(self) -> None:
        """Deletes all stored data (used by the seed and reset scripts)."""
        self.reset()

    # --- Customers ----------------------------------------------------------

    def upsert_customer(self, customer: dict) -> dict:
        self._customers[customer["customer_id"]] = customer
        return customer

    def get_customer(self, customer_id: str) -> dict | None:
        return self._customers.get(customer_id)

    def list_customers(self) -> list[dict]:
        return sorted(self._customers.values(), key=lambda c: c["customer_id"])

    # --- Transactions -------------------------------------------------------

    def add_transaction(self, transaction: dict) -> dict:
        self._transactions[transaction["transaction_id"]] = transaction
        return transaction

    def get_transaction(self, transaction_id: str) -> dict | None:
        return self._transactions.get(transaction_id)

    def list_transactions(self, limit: int = 50, sender_id: str | None = None) -> list[dict]:
        """Newest first, optionally only one sender's transactions."""
        items = [t for t in self._transactions.values() if sender_id in (None, t["sender_id"])]
        items.sort(key=lambda t: t["created_at"], reverse=True)
        return items[:limit]

    def has_paid_before(self, sender_id: str, payee_id: str, before_step: int) -> bool:
        return any(
            t["sender_id"] == sender_id and t["payee_id"] == payee_id and t["step"] < before_step
            for t in self._transactions.values()
        )

    def payee_stats(self, payee_id: str, step: int) -> dict:
        """Payee history as the model expects it (see ml/features.py).

        Only transactions from strictly earlier steps count, only types where
        money flows into the payee, and only payments that were actually sent:
        a held or cancelled payment never reached the payee.
        """
        inflows = [
            t for t in self._transactions.values()
            if t["payee_id"] == payee_id and t["type"] in INFLOW_TYPES and t["step"] < step
            and t["payment_status"] in COMPLETED_STATUSES
        ]
        recent = [t for t in inflows if t["step"] >= step - PAYEE_WINDOW_STEPS]
        return {
            "payee_distinct_senders_before": len({t["sender_id"] for t in inflows}),
            "payee_inflow_count_24h": len(recent),
            "payee_inflow_amount_24h": float(sum(t["amount"] for t in recent)),
        }

    # --- Cases --------------------------------------------------------------

    def create_case(self, case: dict) -> dict:
        case = {"case_id": f"CASE-{uuid.uuid4().hex[:8].upper()}", **case}
        return self.save_case(case)

    def save_case(self, case: dict) -> dict:
        """Stores a new or changed case."""
        self._cases[case["case_id"]] = case
        return case

    def get_case(self, case_id: str) -> dict | None:
        return self._cases.get(case_id)

    def list_cases(self, status: str | None = None, tier: str | None = None, limit: int = 50) -> list[dict]:
        items = [
            c for c in self._cases.values()
            if status in (None, c["status"]) and tier in (None, c["tier"])
        ]
        items.sort(key=lambda c: c["created_at"], reverse=True)
        return items[:limit]


    # --- Chats (one per case, keyed by case_id) -------------------------------

    def get_chat(self, case_id: str) -> dict | None:
        return self._chats.get(case_id)

    def save_chat(self, chat: dict) -> dict:
        self._chats[chat["case_id"]] = chat
        return chat


    # --- Feedback (analyst decisions, kept for retraining) --------------------

    def add_feedback(self, feedback: dict) -> dict:
        self._feedback[feedback["feedback_id"]] = feedback
        return feedback

    def list_feedback(self, limit: int = 200) -> list[dict]:
        items = sorted(self._feedback.values(), key=lambda f: f["decided_at"], reverse=True)
        return items[:limit]


class FirestoreStore(InMemoryStore):
    """InMemoryStore that also persists to Firestore (write-through)."""

    def __init__(self, project: str) -> None:
        from google.cloud import firestore  # imported here so tests need no credentials

        self._firestore = firestore
        self._db = firestore.Client(project=project)
        super().__init__()
        self.load()

    def load(self) -> None:
        """Reads stored data back into memory. Called once at startup."""
        self.reset()
        newest_first = self._firestore.Query.DESCENDING
        for doc in self._db.collection("customers").stream():
            self._customers[doc.id] = doc.to_dict()
        transactions = self._db.collection("transactions").order_by("created_at", direction=newest_first)
        for doc in transactions.limit(MAX_TRANSACTIONS_LOADED).stream():
            self._transactions[doc.id] = doc.to_dict()
        cases = self._db.collection("cases").order_by("created_at", direction=newest_first)
        for doc in cases.limit(MAX_CASES_LOADED).stream():
            self._cases[doc.id] = doc.to_dict()
        chats = self._db.collection("chats").order_by("created_at", direction=newest_first)
        for doc in chats.limit(MAX_CASES_LOADED).stream():
            self._chats[doc.id] = doc.to_dict()
        feedback = self._db.collection("feedback").order_by("decided_at", direction=newest_first)
        for doc in feedback.limit(MAX_CASES_LOADED).stream():
            self._feedback[doc.id] = doc.to_dict()

    def wipe(self) -> None:
        """Deletes every document in the ScamShield collections."""
        for name in COLLECTIONS:
            batch, pending = self._db.batch(), 0
            for doc in self._db.collection(name).stream():
                batch.delete(doc.reference)
                pending += 1
                if pending == 400:  # Firestore allows at most 500 writes per batch
                    batch.commit()
                    batch, pending = self._db.batch(), 0
            if pending:
                batch.commit()
        self.reset()

    def upsert_customer(self, customer: dict) -> dict:
        self._db.collection("customers").document(customer["customer_id"]).set(customer)
        return super().upsert_customer(customer)

    def add_transaction(self, transaction: dict) -> dict:
        self._db.collection("transactions").document(transaction["transaction_id"]).set(transaction)
        return super().add_transaction(transaction)

    def save_case(self, case: dict) -> dict:
        self._db.collection("cases").document(case["case_id"]).set(case)
        return super().save_case(case)

    def save_chat(self, chat: dict) -> dict:
        self._db.collection("chats").document(chat["case_id"]).set(chat)
        return super().save_chat(chat)

    def add_feedback(self, feedback: dict) -> dict:
        self._db.collection("feedback").document(feedback["feedback_id"]).set(feedback)
        return super().add_feedback(feedback)


_store: InMemoryStore | None = None


def get_store() -> InMemoryStore:
    """The process-wide store (FastAPI dependency).

    STORE_BACKEND=firestore or memory. If unset, Firestore is used when
    GOOGLE_CLOUD_PROJECT is configured.
    """
    global _store
    if _store is None:
        from app import config

        if config.STORE_BACKEND == "firestore":
            _store = FirestoreStore(config.GOOGLE_CLOUD_PROJECT)
        else:
            _store = InMemoryStore()
            if config.SEED_ON_START:
                from app.schemas import current_step
                from db.seed_data import seed_store

                seed_store(_store, now_step=current_step())
    return _store
