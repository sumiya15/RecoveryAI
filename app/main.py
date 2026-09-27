from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from app.auth import require_admin
from app.config import (
    get_database_path,
    get_razorpay_webhook_secret,
    is_admin_auth_configured,
    is_insecure_webhook_secret_present,
    load_config,
)
from app.database import get_setting, init_db, set_setting
from app.decision_engine import latest_decisions
from app.metrics import get_metrics, list_audit_logs, list_transactions
from app.recovery import approve_recovery_attempt, latest_recovery_attempts, reject_recovery_attempt
from app.simulator import simulate_one_failed_payment
from app.webhook import router as webhook_router

load_config()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="RecoverAI API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(webhook_router)


@app.get("/api/health")
async def health() -> dict[str, str | bool]:
    return {
        "status": "ok",
        "app": "RecoverAI",
        "mode": "razorpay_test_mode_only",
        "database_path": str(get_database_path()),
        "razorpay_webhook_secret_configured": bool(get_razorpay_webhook_secret()),
        "insecure_webhook_secret_rejected": is_insecure_webhook_secret_present(),
        "admin_auth_configured": is_admin_auth_configured(),
        "gemini_api_key_configured": bool(os.getenv("GEMINI_API_KEY")),
        "recovery_paused": get_setting("recovery_paused", "false") == "true",
    }


@app.get("/api/metrics")
async def metrics(_: None = Depends(require_admin)) -> dict:
    return get_metrics()


@app.get("/api/admin/check")
async def admin_check(_: None = Depends(require_admin)) -> dict[str, bool]:
    return {"authenticated": True}


@app.get("/api/transactions")
async def transactions(_: None = Depends(require_admin), is_synthetic: int | None = Query(default=None)) -> list[dict]:
    return list_transactions(is_synthetic)


@app.get("/api/decisions")
async def decisions(_: None = Depends(require_admin)) -> list[dict]:
    return latest_decisions()


@app.get("/api/recovery-attempts")
async def recovery_attempts(_: None = Depends(require_admin)) -> list[dict]:
    return latest_recovery_attempts()


@app.get("/api/audit-logs")
async def audit_logs(_: None = Depends(require_admin)) -> list[dict]:
    return list_audit_logs()


@app.post("/api/simulate")
async def simulate(_: None = Depends(require_admin)) -> dict:
    return simulate_one_failed_payment()


@app.post("/api/recovery-attempts/{attempt_id}/approve")
async def approve_attempt(attempt_id: int, _: None = Depends(require_admin)) -> dict:
    try:
        return approve_recovery_attempt(attempt_id)
    except ValueError as exc:
        status_code = 404 if "not found" in str(exc).lower() else 409
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@app.post("/api/recovery-attempts/{attempt_id}/reject")
async def reject_attempt(attempt_id: int, _: None = Depends(require_admin)) -> dict:
    try:
        return reject_recovery_attempt(attempt_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/settings/stop-switch")
async def update_stop_switch(enabled: bool, _: None = Depends(require_admin)) -> dict:
    set_setting("recovery_paused", "true" if enabled else "false")
    return {"recovery_paused": enabled}
