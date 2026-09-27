# RecoverAI Validation Checklist

## Webhook Flow

- `POST /webhooks/razorpay` rejects missing `RAZORPAY_WEBHOOK_SECRET`.
- Invalid `X-Razorpay-Signature` returns an error.
- Valid `payment.failed` payload creates a transaction, decision, recovery attempt, and audit log.
- Replaying the same `X-Razorpay-Event-Id` returns `duplicate_ignored`.
- `payment.captured` or `payment.authorized` cancels matching pending reminders by order ID/payment ID.

## Rules

- Recoverable test-mode failures recommend `REMIND`.
- High amount, repeated attempts, unknown failures, or stop switch recommend `ESCALATE` or `STOP`.
- Customer-facing recovery attempts are created with `approval_required`.
- Approval changes status to `approved_demo_only` and does not send a real message.
- Rejection changes status to `rejected` and repeated approval/rejection does not create duplicate actions.
- Stop switch blocks approval of already-pending reminders.

## Dashboard

- Failed payments are listed with source labels.
- Metrics split verified Razorpay webhook data from simulated demo data.
- Suggested actions and approval buttons are visible.
- Audit logs show ingest, decision, recovery, dedupe, and approval activity.
- Stop switch is visible and controls future recovery recommendations.
- Admin token is required before viewing customer-level data or using action buttons.

## Tests

- `python -m pytest` passes.
- Simulated events are clearly marked `simulated_demo`.
- Verified webhook tests use a generated HMAC signature and do not expose secrets.
