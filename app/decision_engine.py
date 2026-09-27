from __future__ import annotations

from dataclasses import dataclass

from app.database import audit, get_db, get_setting, row_to_dict


RECOVERABLE_ERROR_CODES = {
    "BAD_REQUEST_PAYMENT_FAILED",
    "GATEWAY_ERROR",
    "SERVER_ERROR",
}


@dataclass(frozen=True)
class RecoveryDecision:
    id: int
    transaction_id: int
    eligible: bool
    recommended_action: str
    reason: str
    customer_message: str
    needs_approval: bool
    blocked_by_stop_switch: bool


def decide_recovery(transaction_id: int) -> RecoveryDecision:
    with get_db() as conn:
        tx = conn.execute("SELECT * FROM transactions WHERE id = ?", (transaction_id,)).fetchone()
        if tx is None:
            raise ValueError(f"Transaction {transaction_id} not found")

        paused = get_setting("recovery_paused", "false").lower() == "true"
        amount = int(tx["amount"])
        attempt_count = int(tx["attempt_count"])
        error_code = tx["error_code"] or ""

        eligible = (
            not paused
            and tx["status"] == "failed"
            and error_code in RECOVERABLE_ERROR_CODES
            and attempt_count < 3
            and amount <= 1000000
        )

        if paused:
            action = "STOP"
            reason = "Recovery stop switch is enabled."
        elif attempt_count >= 3:
            action = "STOP"
            reason = "Payment has already failed three or more times."
        elif amount > 1000000:
            action = "ESCALATE"
            reason = "Amount is above INR 10,000, so manual review is required."
        elif error_code not in RECOVERABLE_ERROR_CODES:
            action = "ESCALATE"
            reason = "Failure reason is not in the recoverable demo scenario."
        else:
            action = "REMIND"
            reason = "Recoverable test-mode failure with low retry count and safe amount."

        message = (
            "Your payment could not be completed. You can safely retry from your Razorpay checkout link."
            if action == "REMIND"
            else ""
        )

        cursor = conn.execute(
            """
            INSERT INTO decisions(
                transaction_id, eligible, recommended_action, reason, customer_message,
                needs_approval, blocked_by_stop_switch
            )
            VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (
                transaction_id,
                1 if eligible else 0,
                action,
                reason,
                message,
                1 if action == "REMIND" else 0,
                1 if paused else 0,
            ),
        )
        decision_id = cursor.lastrowid
        conn.commit()

    audit(transaction_id, "decision", f"{action}: {reason}")
    return RecoveryDecision(
        id=decision_id,
        transaction_id=transaction_id,
        eligible=eligible,
        recommended_action=action,
        reason=reason,
        customer_message=message,
        needs_approval=action == "REMIND",
        blocked_by_stop_switch=paused,
    )


def latest_decisions() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT d.*, t.razorpay_payment_id, t.amount, t.is_synthetic
            FROM decisions d
            JOIN transactions t ON t.id = d.transaction_id
            ORDER BY d.created_at DESC, d.id DESC
            LIMIT 100
            """
        ).fetchall()
    return [row_to_dict(row) for row in rows]
