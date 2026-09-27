from __future__ import annotations

from uuid import uuid4

from app.webhook import process_failed_payment


def build_demo_failed_payment(
    amount: int = 249900,
    error_code: str = "BAD_REQUEST_PAYMENT_FAILED",
    attempt_count: int = 1,
) -> dict:
    payment_id = f"pay_demo_{uuid4().hex[:14]}"
    return {
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "order_id": f"order_demo_{uuid4().hex[:12]}",
                    "amount": amount,
                    "currency": "INR",
                    "email": "demo.customer@example.com",
                    "contact": "+919999999999",
                    "status": "failed",
                    "error_code": error_code,
                    "error_description": "Demo card/payment attempt failed in test mode.",
                    "attempt_count": attempt_count,
                }
            }
        },
    }


def simulate_one_failed_payment() -> dict:
    event_id = f"evt_demo_{uuid4().hex}"
    payload = build_demo_failed_payment()
    return process_failed_payment(payload, event_id, is_synthetic=True)
