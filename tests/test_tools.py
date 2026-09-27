import hashlib
import hmac
import json
import os
import tempfile
import atexit

from fastapi.testclient import TestClient

fd, TEST_DB = tempfile.mkstemp(prefix="recoverai_pytest_", suffix=".db")
os.close(fd)
os.unlink(TEST_DB)
os.environ["RECOVERAI_DB_PATH"] = TEST_DB
os.environ["RAZORPAY_WEBHOOK_SECRET"] = "test_secret"
os.environ["ALLOW_INSECURE_TEST_SECRETS"] = "true"
os.environ["RECOVERAI_ADMIN_TOKEN"] = "audit_admin_token_123"
atexit.register(lambda: os.path.exists(TEST_DB) and os.unlink(TEST_DB))

from app.main import app
from app.database import init_db
from app.config import PROJECT_ROOT, get_database_path


init_db()
client = TestClient(app)
ADMIN_HEADERS = {"X-RecoverAI-Admin-Token": "audit_admin_token_123"}


def test_simulated_failed_payment_creates_pending_approval():
    response = client.post("/api/simulate", headers=ADMIN_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "simulated_demo"
    assert body["decision"]["recommended_action"] == "REMIND"
    assert body["recovery_attempt"]["outcome"] == "approval_required"


def test_metrics_separates_demo_data():
    client.post("/api/simulate", headers=ADMIN_HEADERS)
    response = client.get("/api/metrics", headers=ADMIN_HEADERS)

    assert response.status_code == 200
    metrics = response.json()
    assert metrics["simulated_demo"]["failed"] >= 1
    assert "signature_validated_webhook" in metrics
    assert "Signature validation does not prove live Razorpay delivery" in metrics["data_note"]


def test_sensitive_routes_require_admin_token():
    response = client.post("/api/simulate")
    wrong = client.get("/api/admin/check", headers={"X-RecoverAI-Admin-Token": "wrong"})
    correct = client.get("/api/admin/check", headers=ADMIN_HEADERS)
    metrics_missing = client.get("/api/metrics")
    metrics_wrong = client.get("/api/metrics", headers={"X-RecoverAI-Admin-Token": "wrong"})
    metrics_correct = client.get("/api/metrics", headers=ADMIN_HEADERS)
    assert response.status_code == 401
    assert wrong.status_code == 401
    assert correct.status_code == 200
    assert metrics_missing.status_code == 401
    assert metrics_wrong.status_code == 401
    assert metrics_correct.status_code == 200


def test_database_path_uses_configured_temp_path():
    assert str(get_database_path()) == TEST_DB


def test_relative_database_path_resolves_from_project(monkeypatch):
    monkeypatch.setenv("RECOVERAI_DB_PATH", "relative_test.db")
    from app.config import get_database_path as resolve_db_path

    assert resolve_db_path() == PROJECT_ROOT / "relative_test.db"


def test_razorpay_webhook_signature_and_dedupe(monkeypatch):
    secret = "test_secret"
    payload = {
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_verified_test_1",
                    "order_id": "order_verified_test_1",
                    "amount": 99900,
                    "currency": "INR",
                    "email": "verified@example.com",
                    "contact": "+919999999999",
                    "status": "failed",
                    "error_code": "BAD_REQUEST_PAYMENT_FAILED",
                    "error_description": "Test failure",
                    "attempt_count": 1,
                }
            }
        },
    }
    raw = json.dumps(payload).encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    headers = {
        "X-Razorpay-Signature": signature,
        "X-Razorpay-Event-Id": "evt_verified_test_1",
    }

    first = client.post("/webhooks/razorpay", content=raw, headers=headers)
    second = client.post("/webhooks/razorpay", content=raw, headers=headers)

    assert first.status_code == 200
    assert first.json()["source"] == "signature_validated_webhook"
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate_ignored"


def test_reject_is_idempotent_and_prevents_later_approval():
    created = client.post("/api/simulate", headers=ADMIN_HEADERS).json()
    attempt_id = created["recovery_attempt"]["id"]

    first_reject = client.post(f"/api/recovery-attempts/{attempt_id}/reject", headers=ADMIN_HEADERS)
    second_reject = client.post(f"/api/recovery-attempts/{attempt_id}/reject", headers=ADMIN_HEADERS)
    approve_after_reject = client.post(f"/api/recovery-attempts/{attempt_id}/approve", headers=ADMIN_HEADERS)

    assert first_reject.status_code == 200
    assert second_reject.status_code == 200
    assert first_reject.json()["outcome"] == "rejected"
    assert second_reject.json()["outcome"] == "rejected"
    assert approve_after_reject.json()["outcome"] == "rejected"


def test_stop_switch_blocks_existing_pending_approval():
    created = client.post("/api/simulate", headers=ADMIN_HEADERS).json()
    attempt_id = created["recovery_attempt"]["id"]

    client.post("/api/settings/stop-switch", params={"enabled": "true"}, headers=ADMIN_HEADERS)
    blocked = client.post(f"/api/recovery-attempts/{attempt_id}/approve", headers=ADMIN_HEADERS)
    stopped_new = client.post("/api/simulate", headers=ADMIN_HEADERS)
    client.post("/api/settings/stop-switch", params={"enabled": "false"}, headers=ADMIN_HEADERS)

    assert blocked.status_code == 409
    assert "stop switch" in blocked.json()["detail"]
    assert stopped_new.json()["decision"]["recommended_action"] == "STOP"
    assert stopped_new.json()["recovery_attempt"]["outcome"] == "no_customer_action"


def test_success_event_cancels_pending_recovery_by_order_id():
    failed_raw = json.dumps(
        {
            "event": "payment.failed",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_cancel_failed",
                        "order_id": "order_cancel_match",
                        "amount": 99000,
                        "currency": "INR",
                        "status": "failed",
                        "error_code": "BAD_REQUEST_PAYMENT_FAILED",
                        "error_description": "Test failure",
                        "attempt_count": 1,
                    }
                }
            },
        },
        separators=(",", ":"),
    ).encode("utf-8")
    failed_sig = hmac.new(b"test_secret", failed_raw, hashlib.sha256).hexdigest()
    client.post(
        "/webhooks/razorpay",
        content=failed_raw,
        headers={
            "X-Razorpay-Signature": failed_sig,
            "X-Razorpay-Event-Id": "evt_cancel_failed",
            "Content-Type": "application/json",
        },
    )

    success_raw = json.dumps(
        {
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_cancel_success",
                        "order_id": "order_cancel_match",
                        "amount": 99000,
                        "currency": "INR",
                        "status": "captured",
                    }
                }
            },
        },
        separators=(",", ":"),
    ).encode("utf-8")
    success_sig = hmac.new(b"test_secret", success_raw, hashlib.sha256).hexdigest()
    success = client.post(
        "/webhooks/razorpay",
        content=success_raw,
        headers={
            "X-Razorpay-Signature": success_sig,
            "X-Razorpay-Event-Id": "evt_cancel_success",
            "Content-Type": "application/json",
        },
    )
    attempts = client.get("/api/recovery-attempts", headers=ADMIN_HEADERS).json()
    metrics = client.get("/api/metrics", headers=ADMIN_HEADERS).json()

    assert success.status_code == 200
    assert success.json()["cancelled_pending_reminders"] >= 1
    assert metrics["signature_validated_webhook"]["cancelled_payment_succeeded"] >= 1
    assert any(
        attempt["razorpay_payment_id"] == "pay_cancel_failed"
        and attempt["outcome"] == "cancelled_payment_succeeded"
        for attempt in attempts
    )
