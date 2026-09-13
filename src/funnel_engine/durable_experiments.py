"""Durable, transactional persistence for experiment commands.

This module deliberately does not perform provider writes.  It records intent,
state transitions, and leases so an executor can safely do that work later.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Mapping
    from pathlib import Path


class IdempotencyConflict(ValueError):
    """The idempotency key was reused for a different command."""


class StateConflict(ValueError):
    """An optimistic status or revision check failed."""


@dataclass(frozen=True)
class Revision:
    experiment_id: str
    revision: int
    hypothesis: str
    operator_intent: str
    proposal: str
    evidence_reference: str | None
    validation: str
    expected_listing_hash: str | None
    rulebook_version: str
    created_by: str
    created_at: str


@dataclass(frozen=True)
class Command:
    command_id: str
    idempotency_key: str
    experiment_id: str
    revision: int
    command_type: str
    state: str
    result: str | None
    error: str | None


def canonical_json(value: Any) -> str:
    """Return stable JSON suitable for equality checks and hashing."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")  # noqa: UP017


def _conn(db_path: str | Path) -> sqlite3.Connection:
    from funnel_engine.db import get_db_connection

    return get_db_connection(db_path)


def migrate_durable_schema(conn: sqlite3.Connection) -> None:
    """Install only new tables/indexes; never rewrite existing application data."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS experiment_revisions (
            experiment_id TEXT NOT NULL REFERENCES experiments(id),
            revision INTEGER NOT NULL CHECK(revision > 0),
            hypothesis TEXT NOT NULL,
            operator_intent TEXT NOT NULL,
            proposal_json TEXT NOT NULL,
            evidence_reference TEXT,
            validation_json TEXT NOT NULL,
            expected_listing_hash TEXT,
            rulebook_version TEXT NOT NULL,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(experiment_id, revision)
        );
        CREATE TABLE IF NOT EXISTS experiment_commands (
            command_id TEXT PRIMARY KEY,
            idempotency_key TEXT NOT NULL UNIQUE,
            experiment_id TEXT NOT NULL REFERENCES experiments(id),
            revision INTEGER NOT NULL,
            command_type TEXT NOT NULL,
            actor TEXT NOT NULL,
            reason TEXT,
            payload_json TEXT NOT NULL,
            semantic_hash TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('pending','processing','completed','failed','reconciliation_required')),
            result_json TEXT,
            error_safe TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT,
            FOREIGN KEY(experiment_id, revision) REFERENCES experiment_revisions(experiment_id, revision)
        );
        CREATE TABLE IF NOT EXISTS experiment_events (
            experiment_id TEXT NOT NULL REFERENCES experiments(id),
            sequence INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            from_status TEXT,
            to_status TEXT,
            actor_type TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            reason_code TEXT,
            reason_text TEXT,
            command_id TEXT REFERENCES experiment_commands(command_id),
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(experiment_id, sequence)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS uq_experiment_event_command
            ON experiment_events(command_id) WHERE command_id IS NOT NULL;
        CREATE TABLE IF NOT EXISTS execution_attempts (
            attempt_id TEXT PRIMARY KEY,
            command_id TEXT NOT NULL REFERENCES experiment_commands(command_id),
            experiment_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            executor TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('claimed','running','completed','failed','expired','reconciliation_required')),
            lease_owner TEXT,
            lease_expires_at TEXT,
            expected_pre_hash TEXT,
            pre_snapshot TEXT,
            post_snapshot TEXT,
            provider_receipt TEXT,
            error_safe TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(experiment_id, revision) REFERENCES experiment_revisions(experiment_id, revision)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS uq_active_attempt_command
            ON execution_attempts(command_id) WHERE state IN ('claimed','running');
        CREATE TRIGGER IF NOT EXISTS experiment_revisions_immutable_update
            BEFORE UPDATE ON experiment_revisions
            BEGIN SELECT RAISE(ABORT, 'experiment revisions are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS experiment_revisions_immutable_delete
            BEFORE DELETE ON experiment_revisions
            BEGIN SELECT RAISE(ABORT, 'experiment revisions are immutable'); END;
        """
    )


def create_revision(
    db_path: str | Path,
    experiment_id: str,
    hypothesis: str,
    operator_intent: str,
    proposal: Any,
    validation: Any,
    rulebook_version: str,
    created_by: str,
    evidence_reference: str | None = None,
    expected_listing_hash: str | None = None,
) -> Revision:
    conn = _conn(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT COALESCE(MAX(revision), 0) + 1 FROM experiment_revisions WHERE experiment_id=?",
                (experiment_id,),
            ).fetchone()
            number = int(row[0])
            created = _now()
            conn.execute(
                "INSERT INTO experiment_revisions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    experiment_id,
                    number,
                    hypothesis,
                    operator_intent,
                    canonical_json(proposal),
                    evidence_reference,
                    canonical_json(validation),
                    expected_listing_hash,
                    rulebook_version,
                    created_by,
                    created,
                ),
            )
            result = Revision(
                experiment_id,
                number,
                hypothesis,
                operator_intent,
                canonical_json(proposal),
                evidence_reference,
                canonical_json(validation),
                expected_listing_hash,
                rulebook_version,
                created_by,
                created,
            )
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()


def _revision(row: sqlite3.Row) -> Revision:
    return Revision(
        *[
            row[k]
            for k in (
                "experiment_id",
                "revision",
                "hypothesis",
                "operator_intent",
                "proposal_json",
                "evidence_reference",
                "validation_json",
                "expected_listing_hash",
                "rulebook_version",
                "created_by",
                "created_at",
            )
        ]
    )


def get_revision(
    db_path: str | Path, experiment_id: str, revision: int | None = None
) -> Revision | None:
    conn = _conn(db_path)
    try:
        query = "SELECT * FROM experiment_revisions WHERE experiment_id=?"
        args: tuple[Any, ...] = (experiment_id,)
        query += " ORDER BY revision DESC LIMIT 1" if revision is None else " AND revision=?"
        if revision is not None:
            args += (revision,)
        row = conn.execute(query, args).fetchone()
        return _revision(row) if row else None
    finally:
        conn.close()


def create_or_return_command(
    db_path: str | Path,
    *,
    command_id: str,
    idempotency_key: str,
    experiment_id: str,
    revision: int,
    command_type: str,
    actor: str,
    reason: str | None,
    payload: Mapping[str, Any],
) -> Command:
    semantic = canonical_hash(
        {
            "experiment_id": experiment_id,
            "revision": revision,
            "command_type": command_type,
            "actor": actor,
            "reason": reason,
            "payload": payload,
        }
    )
    conn = _conn(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        old = conn.execute(
            "SELECT * FROM experiment_commands WHERE idempotency_key=?", (idempotency_key,)
        ).fetchone()
        if old:
            if old["semantic_hash"] != semantic:
                raise IdempotencyConflict(idempotency_key)
            conn.commit()
            return _command(old)
        now = _now()
        conn.execute(
            "INSERT INTO experiment_commands VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                command_id,
                idempotency_key,
                experiment_id,
                revision,
                command_type,
                actor,
                reason,
                canonical_json(payload),
                semantic,
                "pending",
                None,
                None,
                now,
                now,
                None,
            ),
        )
        row = conn.execute(
            "SELECT * FROM experiment_commands WHERE command_id=?", (command_id,)
        ).fetchone()
        conn.commit()
        return _command(row)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _command(row: sqlite3.Row) -> Command:
    return Command(
        row["command_id"],
        row["idempotency_key"],
        row["experiment_id"],
        row["revision"],
        row["command_type"],
        row["state"],
        row["result_json"],
        row["error_safe"],
    )


def claim_command(
    db_path: str | Path, command_id: str, owner: str, lease_seconds: int = 300
) -> dict[str, Any] | None:
    conn = _conn(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        now = datetime.now(timezone.utc)  # noqa: UP017
        now_s = now.isoformat(timespec="microseconds")
        conn.execute(
            "UPDATE execution_attempts SET state='expired', updated_at=? WHERE state IN ('claimed','running') AND lease_expires_at < ?",
            (now_s, now_s),
        )
        conn.execute(
            "UPDATE experiment_commands SET state='pending', updated_at=? WHERE state='processing' AND command_id NOT IN (SELECT command_id FROM execution_attempts WHERE state IN ('claimed','running'))",
            (now_s,),
        )
        cmd = conn.execute(
            "SELECT * FROM experiment_commands WHERE command_id=?", (command_id,)
        ).fetchone()
        if not cmd or cmd["state"] != "pending":
            conn.commit()
            return None
        attempt_id = canonical_hash({"command_id": command_id, "owner": owner, "at": now_s})[:32]
        expiry = (now + timedelta(seconds=lease_seconds)).isoformat(timespec="microseconds")
        conn.execute(
            "UPDATE experiment_commands SET state='processing', updated_at=? WHERE command_id=?",
            (now_s, command_id),
        )
        conn.execute(
            "INSERT INTO execution_attempts (attempt_id,command_id,experiment_id,revision,executor,state,lease_owner,lease_expires_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                attempt_id,
                command_id,
                cmd["experiment_id"],
                cmd["revision"],
                owner,
                "claimed",
                owner,
                expiry,
                now_s,
                now_s,
            ),
        )
        conn.commit()
        return {
            "attempt_id": attempt_id,
            "command_id": command_id,
            "lease_owner": owner,
            "lease_expires_at": expiry,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def append_event(
    db_path: str | Path,
    *,
    experiment_id: str,
    event_type: str,
    to_status: str | None,
    actor_type: str,
    actor_id: str,
    reason_code: str | None = None,
    reason_text: str | None = None,
    command_id: str | None = None,
    payload: Any = None,
    expected_status: str | None = None,
    expected_revision: int | None = None,
) -> int:
    """Append an event and update the legacy status projection atomically."""
    conn = _conn(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        exp = conn.execute("SELECT status FROM experiments WHERE id=?", (experiment_id,)).fetchone()
        if not exp:
            raise StateConflict("experiment does not exist")
        if expected_status is not None and exp["status"] != expected_status:
            raise StateConflict(f"expected status {expected_status}, found {exp['status']}")
        if expected_revision is not None:
            latest = conn.execute(
                "SELECT MAX(revision) FROM experiment_revisions WHERE experiment_id=?",
                (experiment_id,),
            ).fetchone()[0]
            if latest != expected_revision:
                raise StateConflict(f"expected revision {expected_revision}, found {latest}")
        sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM experiment_events WHERE experiment_id=?",
            (experiment_id,),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO experiment_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                experiment_id,
                sequence,
                event_type,
                exp["status"],
                to_status,
                actor_type,
                actor_id,
                reason_code,
                reason_text,
                command_id,
                canonical_json(payload if payload is not None else {}),
                _now(),
            ),
        )
        if to_status is not None:
            conn.execute("UPDATE experiments SET status=? WHERE id=?", (to_status, experiment_id))
        conn.commit()
        return int(sequence)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_event_timeline(db_path: str | Path, experiment_id: str) -> list[dict[str, Any]]:
    conn = _conn(db_path)
    try:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM experiment_events WHERE experiment_id=? ORDER BY sequence",
                (experiment_id,),
            ).fetchall()
        ]
    finally:
        conn.close()


def get_command(db_path: str | Path, command_id: str) -> Command | None:
    conn = _conn(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM experiment_commands WHERE command_id=?", (command_id,)
        ).fetchone()
        return _command(row) if row else None
    finally:
        conn.close()


def finish_command(
    db_path: str | Path,
    command_id: str,
    attempt_id: str,
    *,
    result: Any = None,
    error: str | None = None,
    reconciliation_required: bool = False,
) -> None:
    """Finish an attempt and its command, retaining safe provider error text."""
    state = (
        "reconciliation_required"
        if reconciliation_required
        else ("failed" if error else "completed")
    )
    attempt_state = (
        "reconciliation_required"
        if reconciliation_required
        else ("failed" if error else "completed")
    )
    conn = _conn(db_path)
    try:
        with conn:
            attempt = conn.execute(
                "SELECT state FROM execution_attempts WHERE attempt_id=? AND command_id=?",
                (attempt_id, command_id),
            ).fetchone()
            if not attempt:
                raise StateConflict("attempt does not belong to command")
            now = _now()
            conn.execute(
                "UPDATE execution_attempts SET state=?, error_safe=?, provider_receipt=?, updated_at=? WHERE attempt_id=?",
                (
                    attempt_state,
                    error,
                    canonical_json(result) if result is not None else None,
                    now,
                    attempt_id,
                ),
            )
            conn.execute(
                "UPDATE experiment_commands SET state=?, result_json=?, error_safe=?, updated_at=?, completed_at=? WHERE command_id=?",
                (
                    state,
                    canonical_json(result) if result is not None else None,
                    error,
                    now,
                    now,
                    command_id,
                ),
            )
    finally:
        conn.close()


def complete_command(
    db_path: str | Path, command_id: str, attempt_id: str, result: Any = None
) -> None:
    finish_command(db_path, command_id, attempt_id, result=result)


def fail_command(db_path: str | Path, command_id: str, attempt_id: str, error: str) -> None:
    finish_command(db_path, command_id, attempt_id, error=error)


def mark_reconciliation_required(
    db_path: str | Path, command_id: str, attempt_id: str, error: str
) -> None:
    finish_command(db_path, command_id, attempt_id, error=error, reconciliation_required=True)
