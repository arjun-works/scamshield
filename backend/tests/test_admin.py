from fastapi.testclient import TestClient

from app import config, main
from db.store import get_store

client = TestClient(main.app)


def test_reset_is_off_without_a_configured_token(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_TOKEN", "")
    assert client.post("/admin/reset", headers={"X-Admin-Token": ""}).status_code == 403


def test_reset_needs_the_right_token_and_reseeds(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_TOKEN", "test-token")
    store = get_store()
    store.reset()
    store.add_transaction({
        "transaction_id": "T-OLD", "sender_id": "X", "payee_id": "Y", "type": "TRANSFER", "amount": 1.0,
        "step": 1, "created_at": "2026-01-01T00:00:00+00:00", "payment_status": "allowed",
    })

    assert client.post("/admin/reset").status_code == 401
    assert client.post("/admin/reset", headers={"X-Admin-Token": "nope"}).status_code == 401
    assert store.get_transaction("T-OLD") is not None

    summary = client.post("/admin/reset", headers={"X-Admin-Token": "test-token"}).json()
    assert summary == {"customers": 30, "transactions": 360, "tiers": {"Low": 360}}
    assert store.get_transaction("T-OLD") is None
    assert len(store.list_customers()) == 30
    store.reset()
