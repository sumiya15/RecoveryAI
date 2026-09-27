from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from typing import Iterator

from app.config import get_database_path


DB_PATH = get_database_path()


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                razorpay_payment_id TEXT UNIQUE,
                razorpay_order_id TEXT,
                amount INTEGER NOT NULL,
                currency TEXT NOT NULL DEFAULT 'INR',
                customer_email TEXT,
                customer_contact TEXT,
                status TEXT NOT NULL,
                error_code TEXT,
                error_description TEXT,
                attempt_count INTEGER NOT NULL DEFAULT 1,
                is_synthetic INTEGER NOT NULL DEFAULT 0,
                recovery_status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS webhook_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                razorpay_event_id TEXT UNIQUE NOT NULL,
                event_type TEXT,
                payload TEXT NOT NULL,
                processing_status TEXT NOT NULL,
                received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                processed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_id INTEGER NOT NULL,
                eligible INTEGER NOT NULL,
                recommended_action TEXT NOT NULL,
                reason TEXT NOT NULL,
                customer_message TEXT,
                needs_approval INTEGER NOT NULL DEFAULT 1,
                blocked_by_stop_switch INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(transaction_id) REFERENCES transactions(id)
            );

            CREATE TABLE IF NOT EXISTS recovery_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_id INTEGER NOT NULL,
                decision_id INTEGER NOT NULL,
                action_taken TEXT NOT NULL,
                outcome TEXT NOT NULL,
                approved_by TEXT,
                approved_at TEXT,
                rejected_by TEXT,
                rejected_at TEXT,
                cancel_reason TEXT,
                cancelled_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(transaction_id, action_taken),
                FOREIGN KEY(transaction_id) REFERENCES transactions(id),
                FOREIGN KEY(decision_id) REFERENCES decisions(id)
            );

            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_id INTEGER,
                stage TEXT NOT NULL,
                details TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        for statement in [
            "ALTER TABLE recovery_attempts ADD COLUMN rejected_by TEXT",
            "ALTER TABLE recovery_attempts ADD COLUMN rejected_at TEXT",
            "ALTER TABLE recovery_attempts ADD COLUMN cancel_reason TEXT",
            "ALTER TABLE recovery_attempts ADD COLUMN cancelled_at TEXT",
        ]:
            try:
                conn.execute(statement)
            except sqlite3.OperationalError:
                pass
        conn.execute(
            "INSERT OR IGNORE INTO settings(key, value) VALUES('recovery_paused', 'false')"
        )
        conn.commit()


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict]:
    return [dict(row) for row in rows]


def audit(transaction_id: int | None, stage: str, details: str) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT INTO audit_logs(transaction_id, stage, details) VALUES(?, ?, ?)",
            (transaction_id, stage, details),
        )
        conn.commit()


def get_setting(key: str, default: str = "") -> str:
    with get_db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO settings(key, value, updated_at)
            VALUES(?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
            """,
            (key, value),
        )
        conn.commit()
