from __future__ import annotations

from app.database import get_db, row_to_dict


def get_metrics() -> dict:
    with get_db() as conn:
        transaction_rows = conn.execute(
            """
            SELECT is_synthetic, status, recovery_status, COUNT(*) AS count, COALESCE(SUM(amount), 0) AS amount
            FROM transactions
            GROUP BY is_synthetic, status, recovery_status
            """
        ).fetchall()
        attempt_rows = conn.execute(
            """
            SELECT t.is_synthetic, r.outcome, COUNT(*) AS count
            FROM recovery_attempts r
            JOIN transactions t ON t.id = r.transaction_id
            GROUP BY t.is_synthetic, r.outcome
            """
        ).fetchall()
        guardrails = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM decisions
            WHERE recommended_action IN ('ESCALATE', 'STOP') OR blocked_by_stop_switch = 1
            """
        ).fetchone()
        pending_approvals = conn.execute(
            "SELECT COUNT(*) AS count FROM recovery_attempts WHERE outcome = 'approval_required'"
        ).fetchone()

    buckets = {
        "signature_validated_webhook": {
            "failed": 0,
            "successful": 0,
            "at_risk_paise": 0,
            "pending_approval": 0,
            "approved_demo_only": 0,
            "cancelled_payment_succeeded": 0,
            "rejected": 0,
        },
        "simulated_demo": {
            "failed": 0,
            "successful": 0,
            "at_risk_paise": 0,
            "pending_approval": 0,
            "approved_demo_only": 0,
            "cancelled_payment_succeeded": 0,
            "rejected": 0,
        },
    }

    for row in transaction_rows:
        key = "simulated_demo" if row["is_synthetic"] else "signature_validated_webhook"
        if row["status"] == "failed" and row["recovery_status"] not in {"payment_succeeded", "cancelled_payment_succeeded"}:
            buckets[key]["failed"] += row["count"]
            buckets[key]["at_risk_paise"] += row["amount"]
        elif row["status"] in {"captured", "authorized"}:
            buckets[key]["successful"] += row["count"]

    for row in attempt_rows:
        key = "simulated_demo" if row["is_synthetic"] else "signature_validated_webhook"
        if row["outcome"] in buckets[key]:
            buckets[key][row["outcome"]] += row["count"]

    return {
        "signature_validated_webhook": buckets["signature_validated_webhook"],
        "simulated_demo": buckets["simulated_demo"],
        "guardrail_blocks": guardrails["count"],
        "pending_approvals": pending_approvals["count"],
        "data_note": "Simulated demo results are not signature-validated webhook results. Signature validation does not prove live Razorpay delivery unless tested through Razorpay/ngrok.",
    }


def list_transactions(is_synthetic: int | None = None) -> list[dict]:
    query = "SELECT * FROM transactions"
    params: tuple = ()
    if is_synthetic is not None:
        query += " WHERE is_synthetic = ?"
        params = (is_synthetic,)
    query += " ORDER BY created_at DESC, id DESC LIMIT 100"
    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()
    return [row_to_dict(row) for row in rows]


def list_audit_logs() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_logs ORDER BY created_at DESC, id DESC LIMIT 150"
        ).fetchall()
    return [row_to_dict(row) for row in rows]
