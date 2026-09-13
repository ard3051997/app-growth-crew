"""Focused persistence tests for durable experiment commands."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from funnel_engine.db import get_db_connection, init_db
from funnel_engine.durable_experiments import (
    IdempotencyConflict,
    StateConflict,
    append_event,
    claim_command,
    complete_command,
    create_or_return_command,
    create_revision,
    get_command,
    get_event_timeline,
    get_revision,
    mark_reconciliation_required,
)


def _database(tmp_path: Any) -> str:
    path = str(tmp_path / "durable.db")
    init_db(path)
    conn = get_db_connection(path)
    conn.execute(
        "INSERT INTO experiments(id,app_package,experiment_type,hypothesis,success_metric) VALUES (?,?,?,?,?)",
        ("exp", "pkg", "metadata", "old", "installs"),
    )
    conn.commit()
    conn.close()
    return path


def test_revision_is_immutable_and_incremented(tmp_path: Any) -> None:
    path = _database(tmp_path)
    first = create_revision(path, "exp", "h1", "intent", {"b": 2, "a": 1}, {}, "r1", "oracle")
    second = create_revision(path, "exp", "h2", "intent", {}, {}, "r1", "oracle")
    assert (first.revision, second.revision) == (1, 2)
    assert get_revision(path, "exp").revision == 2  # type: ignore[union-attr]
    with pytest.raises(sqlite3.IntegrityError):
        conn = get_db_connection(path)
        try:
            conn.execute("UPDATE experiment_revisions SET hypothesis='tampered'")
        finally:
            conn.close()


def test_idempotency_and_conflict(tmp_path: Any) -> None:
    path = _database(tmp_path)
    create_revision(path, "exp", "h", "i", {}, {}, "r", "a")
    kwargs: dict[str, Any] = dict(command_id="c1", idempotency_key="same", experiment_id="exp", revision=1,
                                  command_type="apply", actor="a", reason="because", payload={"x": 1})
    first = create_or_return_command(path, **kwargs)
    assert create_or_return_command(path, **kwargs) == first
    with pytest.raises(IdempotencyConflict):
        create_or_return_command(path, **{**kwargs, "command_id": "c2", "payload": {"x": 2}})


def test_claims_and_expiry_recovery(tmp_path: Any) -> None:
    path = _database(tmp_path)
    create_revision(path, "exp", "h", "i", {}, {}, "r", "a")
    create_or_return_command(path, command_id="c", idempotency_key="k", experiment_id="exp", revision=1,
                             command_type="apply", actor="a", reason=None, payload={})
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda owner: claim_command(path, "c", owner, 30), ("one", "two")))
    assert sum(claim is not None for claim in claims) == 1
    conn = get_db_connection(path)
    conn.execute("UPDATE execution_attempts SET lease_expires_at='2000-01-01T00:00:00+00:00'")
    conn.commit()
    conn.close()
    assert claim_command(path, "c", "recovered") is not None


def test_event_projection_rolls_back_and_command_completion(tmp_path: Any) -> None:
    path = _database(tmp_path)
    create_revision(path, "exp", "h", "i", {}, {}, "r", "a")
    with pytest.raises(StateConflict):
        append_event(path, experiment_id="exp", event_type="bad", to_status="running",
                     actor_type="test", actor_id="a", expected_status="approved", expected_revision=1)
    assert get_event_timeline(path, "exp") == []
    append_event(path, experiment_id="exp", event_type="approved", to_status="approved",
                 actor_type="test", actor_id="a", expected_status="proposed", expected_revision=1)
    create_or_return_command(path, command_id="c", idempotency_key="k", experiment_id="exp", revision=1,
                             command_type="apply", actor="a", reason=None, payload={})
    attempt = claim_command(path, "c", "worker")
    complete_command(path, "c", attempt["attempt_id"], {"receipt": "ok"})  # type: ignore[index]
    assert get_command(path, "c").state == "completed"  # type: ignore[union-attr]
    create_or_return_command(path, command_id="c2", idempotency_key="k2", experiment_id="exp", revision=1,
                             command_type="apply", actor="a", reason=None, payload={})
    attempt = claim_command(path, "c2", "worker")
    mark_reconciliation_required(path, "c2", attempt["attempt_id"], "provider outcome unknown")  # type: ignore[index]
    assert get_command(path, "c2").state == "reconciliation_required"  # type: ignore[union-attr]
