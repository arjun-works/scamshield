from collections import Counter

from fastapi.testclient import TestClient

from app.main import app
from app.schemas import TransactionIn, current_step
from app.service import build_customer_context
from db.seed_data import generate_customers, seed_store
from db.store import InMemoryStore, get_store

client = TestClient(app)


def test_customers_are_synthetic_and_deterministic():
    customers = generate_customers()
    assert customers == generate_customers()
    assert len(customers) == 30
    assert Counter(c["preferred_language"] for c in customers) == {"English": 12, "Tamil": 10, "Hindi": 8}
    assert all(c["synthetic"] for c in customers)
    assert all(c["typical_amount_min"] < c["typical_amount_max"] < c["balance"] for c in customers)
    assert len({c["customer_id"] for c in customers}) == 30


def test_seeded_history_is_ordinary_and_allowed():
    store = InMemoryStore()
    summary = seed_store(store, now_step=current_step())
    assert summary["customers"] == 30
    assert summary["transactions"] == 360
    # Ordinary payments to usual payees must not be flagged.
    assert summary["tiers"] == {"Low": 360}
    assert store.list_cases() == []


def test_customer_context_flags_new_payee_and_unusual_amount():
    store = InMemoryStore()
    seed_store(store, now_step=current_step())
    customer = store.get_customer("CUST-001")
    usual_payee = customer["usual_payees"][0]["payee_id"]

    def payment(payee_id: str, amount: float) -> TransactionIn:
        return TransactionIn(
            type="TRANSFER", amount=amount, sender_id="CUST-001",
            sender_balance_before=customer["balance"], payee_id=payee_id,
        )

    usual = build_customer_context(payment(usual_payee, customer["typical_amount_min"]), store)
    assert usual["known_customer"] and not usual["is_new_payee"] and not usual["above_typical_amount"]

    unusual = build_customer_context(payment("C_STRANGER", customer["typical_amount_max"] * 5), store)
    assert unusual["is_new_payee"] and unusual["above_typical_amount"]
    assert unusual["amount_vs_typical_max"] == 5.0
    assert unusual["source"] == "synthetic customer profile"

    unknown = build_customer_context(payment("X", 10).model_copy(update={"sender_id": "C_PAYSIM"}), store)
    assert unknown == {"known_customer": False}


def test_customer_endpoints():
    store = get_store()
    store.reset()
    seed_store(store, now_step=current_step())

    assert len(client.get("/customers").json()) == 30
    detail = client.get("/customers/CUST-001").json()
    assert detail["customer"]["customer_id"] == "CUST-001"
    assert len(detail["transactions"]) == 12
    assert all(t["sender_id"] == "CUST-001" for t in detail["transactions"])
    assert client.get("/customers/CUST-999").status_code == 404
    store.reset()
