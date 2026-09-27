from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

from app.config import get_razorpay_webhook_secret, is_insecure_webhook_secret_present
from app.database import audit, get_db, row_to_dict
from app.decision_engine import decide_recovery
from app.recovery import cancel_pending_for_success, create_recovery_attempt


router = APIRouter()


def verify_razorpay_signature(raw_body: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def payment_from_payload(payload: dict[str, Any], default_status: str = "failed") -> dict[str, Any]:
    payment = payload.get("payload", {}).get("payment", {}).get("entity", {})
    if not payment:
        raise HTTPException(status_code=400, detail="Missing payment entity in webhook payload.")

    return {
        "razorpay_payment_id": payment.get("id"),
        "razorpay_order_id": payment.get("order_id"),
        "amount": int(payment.get("amount") or 0),
        "currency": payment.get("currency") or "INR",
        "customer_email": payment.get("email"),
        "customer_contact": payment.get("contact"),
        "status": payment.get("status") or default_status,
        "error_code": payment.get("error_code") or "BAD_REQUEST_PAYMENT_FAILED",
        "error_description": payment.get("error_description") or "Payment failed in test mode.",
        "attempt_count": int(payment.get("attempt_count") or 1),
        "is_synthetic": 0,
    }


def process_failed_payment(payload: dict[str, Any], event_id: str, is_synthetic: bool) -> dict:
    payment = payment_from_payload(payload)
    payment["is_synthetic"] = 1 if is_synthetic else 0

    with get_db() as conn:
        existing_event = conn.execute(
            "SELECT * FROM webhook_events WHERE razorpay_event_id = ?", (event_id,)
        ).fetchone()
        if existing_event:
            audit(None, "dedupe", f"Duplicate event ignored: {event_id}")
            return {"status": "duplicate_ignored", "event_id": event_id}

        conn.execute(
            """
            INSERT INTO webhook_events(razorpay_event_id, event_type, payload, processing_status, processed_at)
            VALUES(?, ?, ?, 'processing', CURRENT_TIMESTAMP)
            """,
            (event_id, payload.get("event", "payment.failed"), json.dumps(payload)),
        )
        cursor = conn.execute(
            """
            INSERT INTO transactions(
                razorpay_payment_id, razorpay_order_id, amount, currency, customer_email,
                customer_contact, status, error_code, error_description, attempt_count,
                is_synthetic
            )
            VALUES(?, ?, ?, ?, ?, ?, 'failed', ?, ?, ?, ?)
            ON CONFLICT(razorpay_payment_id) DO UPDATE SET
                status = 'failed',
                error_code = excluded.error_code,
                error_description = excluded.error_description,
                attempt_count = excluded.attempt_count
            """,
            (
                payment["razorpay_payment_id"],
                payment["razorpay_order_id"],
                payment["amount"],
                payment["currency"],
                payment["customer_email"],
                payment["customer_contact"],
                payment["error_code"],
                payment["error_description"],
                payment["attempt_count"],
                payment["is_synthetic"],
            ),
        )
        tx = conn.execute(
            "SELECT * FROM transactions WHERE razorpay_payment_id = ?",
            (payment["razorpay_payment_id"],),
        ).fetchone()
        transaction_id = tx["id"] if tx else cursor.lastrowid
        success = None
        if payment["razorpay_order_id"]:
            success = conn.execute(
                """
                SELECT id FROM transactions
                WHERE razorpay_order_id = ?
                  AND (status IN ('captured', 'authorized') OR recovery_status = 'payment_succeeded')
                LIMIT 1
                """,
                (payment["razorpay_order_id"],),
            ).fetchone()
        if success:
            conn.execute(
                "UPDATE transactions SET recovery_status = 'payment_succeeded' WHERE id = ?",
                (transaction_id,),
            )
            conn.execute(
                "UPDATE webhook_events SET processing_status = 'processed', processed_at = CURRENT_TIMESTAMP WHERE razorpay_event_id = ?",
                (event_id,),
            )
            conn.commit()
            audit(
                transaction_id,
                "out_of_order",
                "Failed payment arrived after a matching success; no recovery reminder created.",
            )
            return {
                "status": "received",
                "event_id": event_id,
                "transaction_id": transaction_id,
                "source": "simulated_demo" if is_synthetic else "signature_validated_webhook",
                "recovery_skipped": "matching payment already succeeded",
            }
        conn.execute(
            "UPDATE webhook_events SET processing_status = 'processed', processed_at = CURRENT_TIMESTAMP WHERE razorpay_event_id = ?",
            (event_id,),
        )
        conn.commit()

    audit(
        transaction_id,
        "ingest",
        "Simulated failed payment ingested." if is_synthetic else "Verified Razorpay webhook ingested.",
    )
    decision = decide_recovery(transaction_id)
    attempt = create_recovery_attempt(decision)

    return {
        "status": "received",
        "event_id": event_id,
        "transaction_id": transaction_id,
        "decision": decision.__dict__,
        "recovery_attempt": attempt,
        "source": "simulated_demo" if is_synthetic else "signature_validated_webhook",
    }


def process_successful_payment(payload: dict[str, Any], event_id: str) -> dict:
    payment = payment_from_payload(payload, default_status="captured")
    with get_db() as conn:
        existing_event = conn.execute(
            "SELECT * FROM webhook_events WHERE razorpay_event_id = ?", (event_id,)
        ).fetchone()
        if existing_event:
            audit(None, "dedupe", f"Duplicate event ignored: {event_id}")
            return {"status": "duplicate_ignored", "event_id": event_id}

        conn.execute(
            """
            INSERT INTO webhook_events(razorpay_event_id, event_type, payload, processing_status, processed_at)
            VALUES(?, ?, ?, 'processed', CURRENT_TIMESTAMP)
            """,
            (event_id, payload.get("event", "payment.captured"), json.dumps(payload)),
        )
        conn.execute(
            """
            INSERT INTO transactions(
                razorpay_payment_id, razorpay_order_id, amount, currency, customer_email,
                customer_contact, status, error_code, error_description, attempt_count,
                is_synthetic, recovery_status
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'payment_succeeded')
            ON CONFLICT(razorpay_payment_id) DO UPDATE SET
                status = excluded.status,
                recovery_status = 'payment_succeeded'
            """,
            (
                payment["razorpay_payment_id"],
                payment["razorpay_order_id"],
                payment["amount"],
                payment["currency"],
                payment["customer_email"],
                payment["customer_contact"],
                payment["status"],
                payment["error_code"],
                payment["error_description"],
                payment["attempt_count"],
            ),
        )
        conn.commit()

    cancelled = cancel_pending_for_success(
        payment["razorpay_payment_id"],
        payment["razorpay_order_id"],
    )
    audit(None, "success", f"Signature-validated success event processed; cancelled {cancelled} pending reminders.")
    return {
        "status": "received",
        "event_id": event_id,
        "source": "signature_validated_webhook",
        "cancelled_pending_reminders": cancelled,
    }


@router.post("/webhooks/razorpay")
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: str | None = Header(default=None),
    x_razorpay_event_id: str | None = Header(default=None),
) -> dict:
    if is_insecure_webhook_secret_present():
        raise HTTPException(
            status_code=500,
            detail="RAZORPAY_WEBHOOK_SECRET appears to be a local fake test secret.",
        )
    secret = get_razorpay_webhook_secret()
    if not secret:
        raise HTTPException(status_code=500, detail="RAZORPAY_WEBHOOK_SECRET is not configured.")
    if not x_razorpay_signature:
        raise HTTPException(status_code=400, detail="Missing X-Razorpay-Signature header.")
    if not x_razorpay_event_id:
        raise HTTPException(status_code=400, detail="Missing X-Razorpay-Event-Id header.")

    raw_body = await request.body()
    if not verify_razorpay_signature(raw_body, x_razorpay_signature, secret):
        raise HTTPException(status_code=400, detail="Invalid Razorpay webhook signature.")

    payload = json.loads(raw_body.decode("utf-8"))
    if payload.get("event") in {"payment.captured", "payment.authorized"}:
        return process_successful_payment(payload, x_razorpay_event_id)
    if payload.get("event") != "payment.failed":
        return {"status": "ignored", "event": payload.get("event")}

    return process_failed_payment(payload, x_razorpay_event_id, is_synthetic=False)
