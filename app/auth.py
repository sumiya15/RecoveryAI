from __future__ import annotations

import hmac

from fastapi import Header, HTTPException

from app.config import get_admin_token


def require_admin(x_recoverai_admin_token: str | None = Header(default=None)) -> None:
    expected = get_admin_token()
    if not expected:
        raise HTTPException(status_code=503, detail="RECOVERAI_ADMIN_TOKEN is not configured.")
    if not x_recoverai_admin_token or not hmac.compare_digest(x_recoverai_admin_token, expected):
        raise HTTPException(status_code=401, detail="Admin authentication required.")
