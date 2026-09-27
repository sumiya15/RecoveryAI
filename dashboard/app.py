from __future__ import annotations

import os

import pandas as pd
import requests
import streamlit as st


API_BASE = os.getenv("RECOVERAI_API_BASE", "http://127.0.0.1:8000")


def admin_headers() -> dict[str, str]:
    token = st.session_state.get("applied_admin_token", "")
    return {"X-RecoverAI-Admin-Token": token} if token else {}


def api_get(path: str):
    response = requests.get(f"{API_BASE}{path}", headers=admin_headers(), timeout=10)
    response.raise_for_status()
    return response.json()


def api_post(path: str, params: dict | None = None):
    response = requests.post(f"{API_BASE}{path}", params=params, headers=admin_headers(), timeout=20)
    response.raise_for_status()
    return response.json()


def has_valid_admin_token() -> bool:
    try:
        response = requests.get(f"{API_BASE}/api/admin/check", headers=admin_headers(), timeout=10)
    except requests.RequestException:
        return False
    st.session_state["last_auth_status_code"] = response.status_code
    return response.status_code == 200


def apply_token() -> None:
    pending = st.session_state.get("pending_admin_token", "")
    st.session_state["applied_admin_token"] = pending.strip()


def clear_token() -> None:
    st.session_state["pending_admin_token"] = ""
    st.session_state["applied_admin_token"] = ""
    st.session_state["last_auth_status_code"] = None


st.set_page_config(page_title="RecoverAI", layout="wide")
st.title("RecoverAI")
st.caption("Razorpay test-mode revenue recovery. Demo data is separated from signature-validated webhook data.")

with st.sidebar:
    st.header("Admin")
    st.text_input(
        "Admin token",
        type="password",
        key="pending_admin_token",
        help="Paste the token from your .env, then click Apply token. Editing this field alone does not unlock the dashboard.",
    )
    st.button("Apply token", on_click=apply_token, use_container_width=True)
    st.button("Clear token", on_click=clear_token, use_container_width=True)
    st.caption("Token edits require clicking Apply token.")

health = api_get("/api/health")
paused = bool(health.get("recovery_paused", False))
admin_ready = bool(health.get("admin_auth_configured"))
admin_authenticated = admin_ready and has_valid_admin_token()
token_applied = bool(st.session_state.get("applied_admin_token", ""))
if not admin_ready:
    st.warning("RECOVERAI_ADMIN_TOKEN is not configured. Sensitive dashboard actions and data routes are locked.")
elif not token_applied:
    st.warning("Enter your admin token in the sidebar and click Apply token.")
elif not admin_authenticated:
    status_code = st.session_state.get("last_auth_status_code")
    if status_code in {401, 403}:
        st.warning("Invalid admin token. Protected data and actions are locked.")
    else:
        st.warning("Could not validate the admin token because the backend is unreachable or returned an unexpected error.")

left, right = st.columns([3, 1])
with left:
    st.info("Customer-facing recovery actions require approval. No real messages, charges, or payment links are sent.")
with right:
    new_paused = st.toggle("Stop switch", value=paused, disabled=not admin_authenticated)
    if admin_authenticated and new_paused != paused:
        api_post("/api/settings/stop-switch", {"enabled": str(new_paused).lower()})
        st.rerun()

if st.button("Simulate one recoverable failed payment", type="primary", disabled=not admin_authenticated):
    result = api_post("/api/simulate")
    st.success(f"Created demo transaction {result['transaction_id']} with action {result['decision']['recommended_action']}.")

if admin_authenticated:
    metrics = api_get("/api/metrics")
    validated = metrics["signature_validated_webhook"]
    demo = metrics["simulated_demo"]

    cols = st.columns(5)
    cols[0].metric("Signature-validated failed", validated["failed"])
    cols[1].metric("Validated at risk", f"INR {validated['at_risk_paise'] / 100:,.2f}")
    cols[2].metric("Demo failed", demo["failed"])
    cols[3].metric("Pending approvals", metrics["pending_approvals"])
    cols[4].metric("Guardrail blocks", metrics["guardrail_blocks"])
else:
    st.subheader("Metrics")
    st.write("Protected until a valid admin token is applied.")

st.subheader("Failed Payments")
transactions = api_get("/api/transactions") if admin_authenticated else []
if transactions:
    df = pd.DataFrame(transactions)
    df["source"] = df["is_synthetic"].map({0: "Signature-validated webhook", 1: "Simulated demo data"})
    st.dataframe(df, use_container_width=True, hide_index=True)
else:
    st.write("No failed payments yet.")

st.subheader("Suggested Recovery Actions")
attempts = api_get("/api/recovery-attempts") if admin_authenticated else []
if attempts:
    for attempt in attempts:
        label = "Demo" if attempt["is_synthetic"] else "Signature-validated"
        with st.expander(f"{label} payment {attempt['razorpay_payment_id']} - {attempt['action_taken']} - {attempt['outcome']}"):
            st.json(attempt)
            if attempt["outcome"] == "approval_required":
                approve_col, reject_col = st.columns(2)
                with approve_col:
                    if st.button("Approve demo reminder", key=f"approve-{attempt['id']}", disabled=paused):
                        api_post(f"/api/recovery-attempts/{attempt['id']}/approve")
                        st.rerun()
                with reject_col:
                    if st.button("Reject", key=f"reject-{attempt['id']}"):
                        api_post(f"/api/recovery-attempts/{attempt['id']}/reject")
                        st.rerun()
else:
    st.write("No recovery attempts yet.")

st.subheader("Rules Decisions")
decisions = api_get("/api/decisions") if admin_authenticated else []
if decisions:
    st.dataframe(pd.DataFrame(decisions), use_container_width=True, hide_index=True)
else:
    st.write("No decisions yet.")

st.subheader("Audit Log")
logs = api_get("/api/audit-logs") if admin_authenticated else []
if logs:
    st.dataframe(pd.DataFrame(logs), use_container_width=True, hide_index=True)
else:
    st.write("No audit events yet.")
