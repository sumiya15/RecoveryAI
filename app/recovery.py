from __future__ import annotations

from app.database import audit, get_db, row_to_dict
from app.database import get_setting
from app.decision_engine import RecoveryDecision


def create_recovery_attempt(decision: RecoveryDecision) -> dict:
    outcome = (
        "approval_required"
        if decision.recommended_action == "REMIND" and decision.needs_approval
        else "no_customer_action"
    )

    with get_db() as conn:
        existing = conn.execute(
            """
            SELECT * FROM recovery_attempts
            WHERE transaction_id = ? AND action_taken = ?
            """,
            (decision.transaction_id, decision.recommended_action),
        ).fetchone()
        if existing:
            audit(decision.transaction_id, "dedupe", "Duplicate recovery action ignored.")
            return row_to_dict(existing)

        cursor = conn.execute(
            """
            INSERT INTO recovery_attempts(transaction_id, decision_id, action_taken, outcome)
            VALUES(?, ?, ?, ?)
            """,
            (decision.transaction_id, decision.id, decision.recommended_action, outcome),
        )
        conn.execute(
            "UPDATE transactions SET recovery_status = ? WHERE id = ?",
            (outcome, decision.transaction_id),
        )
        conn.commit()
        attempt_id = cursor.lastrowid

    audit(
        decision.transaction_id,
        "recovery",
        f"{decision.recommended_action} recorded as {outcome}; no real message or charge was sent.",
    )
    return get_recovery_attempt(attempt_id)


def get_recovery_attempt(attempt_id: int) -> dict:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM recovery_attempts WHERE id = ?", (attempt_id,)).fetchone()
    if row is None:
        raise ValueError(f"Recovery attempt {attempt_id} not found")
    return row_to_dict(row)


def approve_recovery_attempt(attempt_id: int, approved_by: str = "demo_user") -> dict:
    if get_setting("recovery_paused", "false").lower() == "true":
        raise ValueError("Recovery stop switch is enabled; pending actions cannot be approved.")

    with get_db() as conn:
        attempt = conn.execute(
            "SELECT * FROM recovery_attempts WHERE id = ?", (attempt_id,)
        ).fetchone()
        if attempt is None:
            raise ValueError(f"Recovery attempt {attempt_id} not found")
        if attempt["outcome"] in {"approved_demo_only", "rejected", "cancelled_payment_succeeded"}:
            return row_to_dict(attempt)
        if attempt["outcome"] != "approval_required":
            return row_to_dict(attempt)

        conn.execute(
            """
            UPDATE recovery_attempts
            SET outcome = 'approved_demo_only', approved_by = ?, approved_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (approved_by, attempt_id),
        )
        conn.execute(
            "UPDATE transactions SET recovery_status = 'approved_demo_only' WHERE id = ?",
            (attempt["transaction_id"],),
        )
        conn.commit()

    audit(
        attempt["transaction_id"],
        "approval",
        "Customer-facing reminder approved in demo mode only; no real message was sent.",
    )
    return get_recovery_attempt(attempt_id)


def reject_recovery_attempt(attempt_id: int, rejected_by: str = "demo_user") -> dict:
    with get_db() as conn:
        attempt = conn.execute(
            "SELECT * FROM recovery_attempts WHERE id = ?", (attempt_id,)
        ).fetchone()
        if attempt is None:
            raise ValueError(f"Recovery attempt {attempt_id} not found")
        if attempt["outcome"] in {"approved_demo_only", "rejected", "cancelled_payment_succeeded"}:
            return row_to_dict(attempt)
        if attempt["outcome"] != "approval_required":
            return row_to_dict(attempt)

        conn.execute(
            """
            UPDATE recovery_attempts
            SET outcome = 'rejected', rejected_by = ?, rejected_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (rejected_by, attempt_id),
        )
        conn.execute(
            "UPDATE transactions SET recovery_status = 'rejected' WHERE id = ?",
            (attempt["transaction_id"],),
        )
        conn.commit()

    audit(attempt["transaction_id"], "rejection", "Pending recovery reminder was rejected.")
    return get_recovery_attempt(attempt_id)


def cancel_pending_for_success(razorpay_payment_id: str | None, razorpay_order_id: str | None) -> int:
    with get_db() as conn:
        clauses = []
        params: list[str] = []
        if razorpay_order_id:
            clauses.append("razorpay_order_id = ?")
            params.append(razorpay_order_id)
        if razorpay_payment_id:
            clauses.append("razorpay_payment_id = ?")
            params.append(razorpay_payment_id)
        if not clauses:
            return 0

        tx_rows = conn.execute(
            f"SELECT id FROM transactions WHERE {' OR '.join(clauses)}",
            params,
        ).fetchall()
        tx_ids = [row["id"] for row in tx_rows]
        cancelled = 0
        for tx_id in tx_ids:
            cursor = conn.execute(
                """
                UPDATE recovery_attempts
                SET outcome = 'cancelled_payment_succeeded',
                    cancel_reason = 'matching successful payment event',
                    cancelled_at = CURRENT_TIMESTAMP
                WHERE transaction_id = ? AND outcome = 'approval_required'
                """,
                (tx_id,),
            )
            cancelled += cursor.rowcount
            if cursor.rowcount:
                conn.execute(
                    "UPDATE transactions SET recovery_status = 'payment_succeeded' WHERE id = ?",
                    (tx_id,),
                )
        conn.commit()

    for tx_id in tx_ids:
        audit(tx_id, "success", "Matching successful payment event cancelled pending recovery reminders.")
    return cancelled


def latest_recovery_attempts() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT r.*, t.razorpay_payment_id, t.amount, t.is_synthetic
            FROM recovery_attempts r
            JOIN transactions t ON t.id = r.transaction_id
            ORDER BY r.created_at DESC, r.id DESC
            LIMIT 100
            """
        ).fetchall()
    return [row_to_dict(row) for row in rows]
