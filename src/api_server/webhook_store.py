"""Durable webhook receipt and outbox claims stored in SQLite."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from funnel_engine.db import DEFAULT_DB_PATH, get_db_connection

if TYPE_CHECKING:
    from pathlib import Path

CLAIM_TTL = timedelta(minutes=10)
DEFAULT_MAX_ATTEMPTS = 5
RETRY_BASE_DELAY = timedelta(seconds=30)
RETRY_MAX_DELAY = timedelta(hours=1)


def _hash_event_id(event_id: str) -> str:
    return hashlib.sha256(event_id.encode()).hexdigest()


def _create_table(conn: Any) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS webhook_event_receipts (
            provider TEXT NOT NULL,
            event_id_hash TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            state TEXT NOT NULL CHECK(
                state IN ('pending', 'processing', 'completed', 'failed', 'dead_letter')
            ),
            attempts INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 5,
            claim_token TEXT,
            claim_expires_at TEXT,
            next_attempt_at TEXT,
            last_error_safe TEXT,
            received_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT,
            PRIMARY KEY (provider, event_id_hash)
        );
        """
    )


def _ensure_table(conn: Any) -> None:
    existing = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'webhook_event_receipts';"
    ).fetchone()
    _create_table(conn)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(webhook_event_receipts);")}
    legacy_receipts = existing is not None and "state" not in columns
    migrations = {
        "payload_json": "TEXT NOT NULL DEFAULT '{}'",
        "state": "TEXT NOT NULL DEFAULT 'pending'",
        "attempts": "INTEGER NOT NULL DEFAULT 0",
        "max_attempts": f"INTEGER NOT NULL DEFAULT {DEFAULT_MAX_ATTEMPTS}",
        "claim_token": "TEXT",
        "claim_expires_at": "TEXT",
        "next_attempt_at": "TEXT",
        "last_error_safe": "TEXT",
        "updated_at": "TEXT",
        "completed_at": "TEXT",
    }
    for column, column_type in migrations.items():
        if column not in columns:
            conn.execute(f"ALTER TABLE webhook_event_receipts ADD COLUMN {column} {column_type};")
    if legacy_receipts:
        conn.execute(
            """
            UPDATE webhook_event_receipts
            SET state = 'completed', completed_at = COALESCE(completed_at, received_at),
                updated_at = COALESCE(updated_at, received_at);
            """
        )
    conn.execute(
        """
        UPDATE webhook_event_receipts
        SET state = COALESCE(state, 'completed'),
            payload_json = COALESCE(payload_json, '{}'),
            max_attempts = COALESCE(max_attempts, 5),
            updated_at = COALESCE(updated_at, received_at),
            completed_at = CASE
                WHEN state IS NULL THEN COALESCE(completed_at, received_at)
                ELSE completed_at
            END
        WHERE state IS NULL OR payload_json IS NULL OR updated_at IS NULL;
        """
    )
    table_sql_row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'webhook_event_receipts';"
    ).fetchone()
    table_sql = str(table_sql_row[0] or "") if table_sql_row else ""
    if "dead_letter" not in table_sql:
        conn.execute(
            "ALTER TABLE webhook_event_receipts RENAME TO webhook_event_receipts_before_retry;"
        )
        _create_table(conn)
        conn.execute(
            """
            INSERT INTO webhook_event_receipts (
                provider, event_id_hash, payload_json, state, attempts, max_attempts,
                claim_token, claim_expires_at, next_attempt_at, last_error_safe,
                received_at, updated_at, completed_at
            )
            SELECT provider, event_id_hash, payload_json,
                   CASE WHEN state IN ('pending', 'processing', 'completed', 'failed')
                        THEN state ELSE 'completed' END,
                   attempts, max_attempts, claim_token, claim_expires_at, next_attempt_at,
                   last_error_safe, received_at, updated_at, completed_at
            FROM webhook_event_receipts_before_retry;
            """
        )
        conn.execute("DROP TABLE webhook_event_receipts_before_retry;")
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_webhook_receipts_due
        ON webhook_event_receipts(provider, state, next_attempt_at, received_at);
        """
    )


def _dead_letter_exhausted_claims(conn: Any, now_text: str) -> None:
    conn.execute(
        """
        UPDATE webhook_event_receipts
        SET state = 'dead_letter', claim_token = NULL, claim_expires_at = NULL,
            next_attempt_at = NULL, updated_at = ?
        WHERE state = 'processing' AND attempts >= max_attempts
          AND (claim_expires_at IS NULL OR claim_expires_at <= ?);
        """,
        (now_text, now_text),
    )


def claim_webhook_event(
    provider: str,
    event_id: str,
    payload_json: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> tuple[str, str | None]:
    """Persist work and atomically claim it only when its retry schedule is due."""
    event_id_hash = _hash_event_id(event_id)
    now = datetime.now(UTC)
    now_text = now.isoformat()
    expires_at = (now + CLAIM_TTL).isoformat()
    claim_token = uuid.uuid4().hex
    conn = get_db_connection(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE;")
        _ensure_table(conn)
        _dead_letter_exhausted_claims(conn, now_text)
        conn.execute(
            """
            INSERT OR IGNORE INTO webhook_event_receipts (
                provider, event_id_hash, payload_json, state, received_at, updated_at
            ) VALUES (?, ?, ?, 'pending', ?, ?);
            """,
            (provider, event_id_hash, payload_json, now_text, now_text),
        )
        row = conn.execute(
            """
            SELECT state, attempts, max_attempts, claim_expires_at, next_attempt_at
            FROM webhook_event_receipts
            WHERE provider = ? AND event_id_hash = ?;
            """,
            (provider, event_id_hash),
        ).fetchone()
        if row is None:
            raise RuntimeError("Webhook receipt disappeared during claim")
        expired = row["state"] == "processing" and (
            not row["claim_expires_at"] or row["claim_expires_at"] <= now_text
        )
        retry_due = not row["next_attempt_at"] or row["next_attempt_at"] <= now_text
        can_attempt = row["attempts"] < row["max_attempts"]
        if can_attempt and ((row["state"] in {"pending", "failed"} and retry_due) or expired):
            cursor = conn.execute(
                """
                UPDATE webhook_event_receipts SET
                    state = 'processing', attempts = attempts + 1, claim_token = ?,
                    claim_expires_at = ?, last_error_safe = NULL, updated_at = ?
                WHERE provider = ? AND event_id_hash = ?
                  AND attempts < max_attempts
                  AND ((state IN ('pending', 'failed')
                        AND (next_attempt_at IS NULL OR next_attempt_at <= ?))
                       OR (state = 'processing'
                           AND (claim_expires_at IS NULL OR claim_expires_at <= ?)));
                """,
                (
                    claim_token,
                    expires_at,
                    now_text,
                    provider,
                    event_id_hash,
                    now_text,
                    now_text,
                ),
            )
            if cursor.rowcount == 1:
                conn.commit()
                return "processing", claim_token
        conn.commit()
        return str(row["state"]), None
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def finish_webhook_event(
    provider: str,
    event_id: str,
    claim_token: str,
    *,
    succeeded: bool,
    error_safe: str | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> bool:
    """Complete or fail only the currently held processing claim."""
    return finish_webhook_receipt(
        provider,
        _hash_event_id(event_id),
        claim_token,
        succeeded=succeeded,
        error_safe=error_safe,
        db_path=db_path,
    )


def finish_webhook_receipt(
    provider: str,
    event_id_hash: str,
    claim_token: str,
    *,
    succeeded: bool,
    error_safe: str | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> bool:
    """Complete or fail a processing claim identified by its stored event hash."""
    now_value = datetime.now(UTC)
    now = now_value.isoformat()
    conn = get_db_connection(db_path)
    try:
        with conn:
            _ensure_table(conn)
            claim = conn.execute(
                """
                SELECT attempts, max_attempts FROM webhook_event_receipts
                WHERE provider = ? AND event_id_hash = ?
                  AND state = 'processing' AND claim_token = ?;
                """,
                (provider, event_id_hash, claim_token),
            ).fetchone()
            if claim is None:
                return False
            if succeeded:
                state = "completed"
                next_attempt_at = None
            elif claim["attempts"] >= claim["max_attempts"]:
                state = "dead_letter"
                next_attempt_at = None
            else:
                state = "failed"
                multiplier = 2 ** max(int(claim["attempts"]) - 1, 0)
                delay = min(RETRY_BASE_DELAY * multiplier, RETRY_MAX_DELAY)
                next_attempt_at = (now_value + delay).isoformat()
            cursor = conn.execute(
                """
                UPDATE webhook_event_receipts SET
                    state = ?, claim_token = NULL, claim_expires_at = NULL,
                    next_attempt_at = ?, last_error_safe = ?, updated_at = ?,
                    completed_at = CASE WHEN ? = 'completed' THEN ? ELSE NULL END
                WHERE provider = ? AND event_id_hash = ?
                  AND state = 'processing' AND claim_token = ?;
                """,
                (
                    state,
                    next_attempt_at,
                    error_safe,
                    now,
                    state,
                    now,
                    provider,
                    event_id_hash,
                    claim_token,
                ),
            )
            return cursor.rowcount == 1
    finally:
        conn.close()


def claim_next_webhook_event(
    provider: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, str] | None:
    """Claim the oldest eligible outbox item without letting delayed failures starve work."""
    now = datetime.now(UTC)
    now_text = now.isoformat()
    expires_at = (now + CLAIM_TTL).isoformat()
    claim_token = uuid.uuid4().hex
    conn = get_db_connection(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE;")
        _ensure_table(conn)
        _dead_letter_exhausted_claims(conn, now_text)
        row = conn.execute(
            """
            SELECT event_id_hash, payload_json FROM webhook_event_receipts
            WHERE provider = ? AND attempts < max_attempts AND (
                (state IN ('pending', 'failed')
                 AND (next_attempt_at IS NULL OR next_attempt_at <= ?))
                OR (state = 'processing' AND (claim_expires_at IS NULL OR claim_expires_at <= ?))
            )
            ORDER BY COALESCE(next_attempt_at, received_at) ASC, received_at ASC
            LIMIT 1;
            """,
            (provider, now_text, now_text),
        ).fetchone()
        if row is None:
            conn.commit()
            return None
        cursor = conn.execute(
            """
            UPDATE webhook_event_receipts SET
                state = 'processing', attempts = attempts + 1, claim_token = ?,
                claim_expires_at = ?, last_error_safe = NULL, updated_at = ?
            WHERE provider = ? AND event_id_hash = ? AND attempts < max_attempts AND (
                (state IN ('pending', 'failed')
                 AND (next_attempt_at IS NULL OR next_attempt_at <= ?))
                OR (state = 'processing' AND (claim_expires_at IS NULL OR claim_expires_at <= ?))
            );
            """,
            (
                claim_token,
                expires_at,
                now_text,
                provider,
                row["event_id_hash"],
                now_text,
                now_text,
            ),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            return None
        conn.commit()
        return {
            "event_id_hash": str(row["event_id_hash"]),
            "payload_json": str(row["payload_json"]),
            "claim_token": claim_token,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
