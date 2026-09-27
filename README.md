# RecoverAI

RecoverAI is a Razorpay test-mode revenue recovery MVP. It receives failed-payment webhooks, validates Razorpay signatures, applies clear recovery rules, records an approval-required recovery suggestion, and shows failed payments, status, metrics, and audit logs in a Streamlit dashboard.

The current MVP is rules-first. It does not call paid OpenAI APIs and does not send real customer messages, create real charges, or present demo revenue as verified Razorpay revenue. Gemini can be added later for optional explanations only.

## Architecture

```text
Razorpay test-mode payment.failed webhook
  -> POST /webhooks/razorpay
  -> HMAC SHA-256 signature validation
  -> SQLite transaction, webhook event, decision, recovery attempt, audit log
  -> Streamlit dashboard

Simulated demo event
  -> POST /api/simulate
  -> same rules and audit path, labelled simulated_demo
```

## Environment

Create a `.env` file in the project root, or copy `.env.example`. Keep it out of git.

```bash
RAZORPAY_WEBHOOK_SECRET=your_test_mode_webhook_secret
RECOVERAI_ADMIN_TOKEN=replace_with_a_long_random_admin_token
GEMINI_API_KEY=optional_for_future_explanations
```

`RECOVERAI_ADMIN_TOKEN` protects endpoints that expose customer/payment data or trigger demo actions. The dashboard sends it as `X-RecoverAI-Admin-Token`.

`RECOVERAI_DB_PATH` is optional. If omitted, RecoverAI uses `recoverai.db` in this project folder, not whatever folder your terminal happens to start in.

## Local Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

In another terminal:

```bash
.venv\Scripts\activate
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Run the dashboard:

```bash
streamlit run dashboard/app.py
```

## API

- `GET /api/health`
- `POST /webhooks/razorpay`
- `POST /api/simulate`
- `GET /api/metrics`
- `GET /api/transactions`
- `GET /api/decisions`
- `GET /api/recovery-attempts`
- `POST /api/recovery-attempts/{attempt_id}/approve`
- `POST /api/settings/stop-switch?enabled=true`
- `GET /api/audit-logs`

Protected admin endpoints require:

```text
X-RecoverAI-Admin-Token: your_admin_token
```

The Razorpay webhook stays public so Razorpay can call it, but it is protected by `X-Razorpay-Signature`.

## Recovery Rules

The MVP focuses on one recoverable failed-payment scenario:

- `status = failed`
- error code is `BAD_REQUEST_PAYMENT_FAILED`, `GATEWAY_ERROR`, or `SERVER_ERROR`
- attempt count is below 3
- amount is INR 10,000 or less
- stop switch is off

Eligible payments get a `REMIND` recommendation and an `approval_required` recovery attempt. Approval records a demo-only approval; it does not send a real customer message.

If the stop switch is on, new recoveries are marked `STOP` and already-pending reminders cannot be approved. Pending reminders can be rejected, and successful payment events cancel matching pending reminders by order ID or payment ID.

## Validation Checklist

See `VALIDATION.md` for the full checklist.

- Razorpay webhook signatures are validated.
- Duplicate webhook event IDs are ignored.
- Simulated demo data is labelled and split from signature-validated webhook data.
- Recovery suggestions require approval before customer-facing action.
- Stop switch blocks new recovery recommendations.
- Tests pass with `pytest`.
