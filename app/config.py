from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"
INSECURE_TEST_SECRETS = {"local_test_webhook_secret", "audit_fake_secret", "test_secret"}


def load_config() -> None:
    load_dotenv(dotenv_path=ENV_PATH, override=False)


def resolve_path(value: str | None, default_name: str) -> Path:
    if value:
        path = Path(value)
        return path if path.is_absolute() else PROJECT_ROOT / path
    return PROJECT_ROOT / default_name


def get_database_path() -> Path:
    return resolve_path(os.getenv("RECOVERAI_DB_PATH"), "recoverai.db")


def _allows_insecure_test_secrets() -> bool:
    return os.getenv("ALLOW_INSECURE_TEST_SECRETS", "false").lower() == "true"


def get_razorpay_webhook_secret() -> str | None:
    secret = os.getenv("RAZORPAY_WEBHOOK_SECRET")
    if not secret:
        return None
    if secret in INSECURE_TEST_SECRETS and not _allows_insecure_test_secrets():
        return None
    return secret


def is_insecure_webhook_secret_present() -> bool:
    secret = os.getenv("RAZORPAY_WEBHOOK_SECRET")
    return bool(secret and secret in INSECURE_TEST_SECRETS and not _allows_insecure_test_secrets())


def get_admin_token() -> str | None:
    token = os.getenv("RECOVERAI_ADMIN_TOKEN")
    if not token:
        return None
    if token in {"change-me", "admin", "password"} and not _allows_insecure_test_secrets():
        return None
    return token


def is_admin_auth_configured() -> bool:
    return get_admin_token() is not None


load_config()
