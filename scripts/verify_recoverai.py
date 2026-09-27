from __future__ import annotations

import hashlib
import hmac
import json
import os
from uuid import uuid4

import requests


API_BASE = "http://127.0.0.1:8000"
WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET")
ADMIN_TOKEN = os.getenv("RECOVERAI_ADMIN_TOKEN")


def main() -> int:
    if not WEBHOOK_SECRET or not ADMIN_TOKEN:
        raise SystemExit("Set RAZORPAY_WEBHOOK_SECRET and RECOVERAI_ADMIN_TOKEN before running verification.")
    admin_headers = {"X-RecoverAI-Admin-Token": ADMIN_TOKEN}
    health = requests.get(f"{API_BASE}/api/health", timeout=10).json()
    print("health:", health)

    demo = requests.post(f"{API_BASE}/api/simulate", headers=admin_headers, timeout=20).json()
    print("simulate:", demo["source"], demo["decision"]["recommended_action"], demo["recovery_attempt"]["outcome"])

    event_id = f"evt_verified_{uuid4().hex}"
    payload = {
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": f"pay_verified_{uuid4().hex[:14]}",
                    "order_id": f"order_verified_{uuid4().hex[:12]}",
                    "amount": 125000,
                    "currency": "INR",
                    "email": "verified.customer@example.com",
                    "contact": "+919999999999",
                    "status": "failed",
                    "error_code": "BAD_REQUEST_PAYMENT_FAILED",
                    "error_description": "Test-mode card failed.",
                    "attempt_count": 1,
                }
            }
        },
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(WEBHOOK_SECRET.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    headers = {
        "X-Razorpay-Signature": signature,
        "X-Razorpay-Event-Id": event_id,
        "Content-Type": "application/json",
    }

    first = requests.post(f"{API_BASE}/webhooks/razorpay", data=raw, headers=headers, timeout=20).json()
    replay = requests.post(f"{API_BASE}/webhooks/razorpay", data=raw, headers=headers, timeout=20).json()
    metrics = requests.get(f"{API_BASE}/api/metrics", timeout=10).json()

    print("webhook:", first["source"], first["decision"]["recommended_action"], first["recovery_attempt"]["outcome"])
    print("replay:", replay["status"])
    print("metrics:", metrics)

    assert health["app"] == "RecoverAI"
    assert health["razorpay_webhook_secret_configured"] is True
    assert demo["source"] == "simulated_demo"
    assert first["source"] == "signature_validated_webhook"
    assert replay["status"] == "duplicate_ignored"
    assert metrics["simulated_demo"]["failed"] >= 1
    assert metrics["signature_validated_webhook"]["failed"] >= 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
