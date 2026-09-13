from __future__ import annotations

import asyncio
import hashlib
import sqlite3
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api_server.main import app
from api_server.routes import webhooks
from api_server.routes.webhooks import RevenueCatEvent, run_fcm_reengagement
from api_server.webhook_store import (
    claim_next_webhook_event,
    claim_webhook_event,
    finish_webhook_event,
    finish_webhook_receipt,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

SECURITY_ENV = (
    "MCP_GC_API_AUTH_REQUIRED",
    "MCP_GC_ADMIN_API_KEY",
    "MCP_GC_VIEWER_API_KEY",
    "MCP_GC_PROXY_SHARED_TOKEN",
    "MCP_GC_READ_ONLY",
    "MCP_GC_REVENUECAT_WEBHOOK_SECRET",
    "MCP_GC_REVENUECAT_WEBHOOK_HEADER",
    "MCP_GC_INSECURE_DEV_WEBHOOKS",
    "MCP_GC_ENV",
    "MCP_GC_CONFIG_WRITES_ENABLED",
    "MCP_GC_DEV_ALLOW_GENERIC_EXECUTABLE_PROPOSALS",
)


@pytest.fixture(autouse=True)
def _clean_security_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in SECURITY_ENV:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def _enable_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_GC_API_AUTH_REQUIRED", "1")
    monkeypatch.setenv("MCP_GC_ADMIN_API_KEY", "admin-test-key")
    monkeypatch.setenv("MCP_GC_VIEWER_API_KEY", "viewer-test-key")
    monkeypatch.setenv("MCP_GC_PROXY_SHARED_TOKEN", "proxy-test-token")


@pytest.mark.parametrize(
    ("method", "path", "headers", "expected_status"),
    [
        ("GET", "/api/system/status", {}, 401),
        ("GET", "/api/system/status", {"Authorization": "Bearer wrong-key"}, 401),
        ("GET", "/api/system/status", {"Authorization": "Bearer viewer-test-key"}, 200),
        ("GET", "/api/system/status", {"Authorization": "Bearer admin-test-key"}, 200),
        ("HEAD", "/api/system/status", {}, 401),
        ("HEAD", "/api/system/status", {"Authorization": "Bearer viewer-test-key"}, 405),
        ("OPTIONS", "/api/system/status", {}, 401),
        (
            "OPTIONS",
            "/api/system/status",
            {"Authorization": "Bearer viewer-test-key"},
            405,
        ),
        (
            "GET",
            "/api/system/status",
            {
                "X-MCP-GC-Proxy-Token": "proxy-test-token",
                "X-MCP-GC-Proxy-Role": "viewer",
            },
            200,
        ),
        ("POST", "/api/experiments/", {"Authorization": "Bearer viewer-test-key"}, 403),
        (
            "POST",
            "/api/experiments/",
            {
                "X-MCP-GC-Proxy-Token": "proxy-test-token",
                "X-MCP-GC-Proxy-Role": "viewer",
            },
            403,
        ),
        ("POST", "/api/experiments/", {"Authorization": "Bearer admin-test-key"}, 422),
        (
            "POST",
            "/api/experiments/",
            {
                "X-MCP-GC-Proxy-Token": "proxy-test-token",
                "X-MCP-GC-Proxy-Role": "admin",
            },
            422,
        ),
    ],
)
def test_route_authorization_matrix(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    method: str,
    path: str,
    headers: dict[str, str],
    expected_status: int,
) -> None:
    _enable_auth(monkeypatch)
    response = client.request(method, path, headers=headers, json={} if method == "POST" else None)
    assert response.status_code == expected_status


def test_health_and_local_default_remain_unauthenticated(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/system/status").status_code == 200

    monkeypatch.setenv("MCP_GC_API_AUTH_REQUIRED", "1")
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/system/status").status_code == 401


def test_secure_cors_preflight_requires_proxy_authentication(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    _enable_auth(monkeypatch)
    preflight_headers = {
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "GET",
    }
    assert client.options("/api/system/status", headers=preflight_headers).status_code == 401

    preflight_headers.update(
        {
            "X-MCP-GC-Proxy-Token": "proxy-test-token",
            "X-MCP-GC-Proxy-Role": "viewer",
        }
    )
    response = client.options("/api/system/status", headers=preflight_headers)
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_forged_revenuecat_webhook_is_rejected(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    _enable_auth(monkeypatch)
    monkeypatch.setenv("MCP_GC_REVENUECAT_WEBHOOK_SECRET", "provider-secret")
    payload = {
        "event": {
            "id": "rc-event-forged",
            "type": "INITIAL_PURCHASE",
            "app_id": "com.example.app",
            "app_user_id": "subscriber-secret",
        }
    }

    assert client.post("/api/webhooks/revenuecat", json=payload).status_code == 401
    response = client.post(
        "/api/webhooks/revenuecat",
        json=payload,
        headers={"Authorization": "Bearer admin-test-key"},
    )
    assert response.status_code == 401


def test_webhook_fails_closed_without_global_auth_and_bypass_is_local_only(
    monkeypatch: pytest.MonkeyPatch, client: TestClient, tmp_path: Path
) -> None:
    payload = {
        "event": {
            "id": "rc-local-bypass",
            "type": "INITIAL_PURCHASE",
            "app_id": "com.example.app",
            "app_user_id": "subscriber-secret",
        }
    }
    assert client.post("/api/webhooks/revenuecat", json=payload).status_code == 401

    monkeypatch.setenv("MCP_GC_INSECURE_DEV_WEBHOOKS", "1")
    with patch("api_server.routes.webhooks.DEFAULT_DB_PATH", tmp_path / "local.db"):
        assert client.post("/api/webhooks/revenuecat", json=payload).status_code == 200

    monkeypatch.setenv("MCP_GC_ENV", "managed")
    assert client.post("/api/webhooks/revenuecat", json=payload).status_code == 401


def test_secure_webhook_requires_secret_configuration_and_event_id(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    _enable_auth(monkeypatch)
    payload = {
        "event": {
            "type": "INITIAL_PURCHASE",
            "app_id": "com.example.app",
            "app_user_id": "subscriber-secret",
        }
    }
    assert client.post("/api/webhooks/revenuecat", json=payload).status_code == 401

    monkeypatch.setenv("MCP_GC_REVENUECAT_WEBHOOK_SECRET", "provider-secret")
    response = client.post(
        "/api/webhooks/revenuecat",
        json=payload,
        headers={"Authorization": "provider-secret"},
    )
    assert response.status_code == 400


def test_revenuecat_webhook_supports_configured_secret_header(
    monkeypatch: pytest.MonkeyPatch, client: TestClient, tmp_path: Path
) -> None:
    _enable_auth(monkeypatch)
    monkeypatch.setenv("MCP_GC_REVENUECAT_WEBHOOK_SECRET", "provider-secret")
    monkeypatch.setenv("MCP_GC_REVENUECAT_WEBHOOK_HEADER", "X-RevenueCat-Secret")
    payload = {
        "event": {
            "id": "rc-event-custom-header",
            "type": "INITIAL_PURCHASE",
            "app_id": "com.example.app",
            "app_user_id": "subscriber-secret",
        }
    }
    db_path = tmp_path / "custom-header-webhook.db"
    with patch("api_server.routes.webhooks.DEFAULT_DB_PATH", db_path):
        response = client.post(
            "/api/webhooks/revenuecat",
            json=payload,
            headers={"X-RevenueCat-Secret": "provider-secret"},
        )
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


def test_revenuecat_replay_is_persisted_and_not_rescheduled(
    monkeypatch: pytest.MonkeyPatch, client: TestClient, tmp_path: Path
) -> None:
    _enable_auth(monkeypatch)
    monkeypatch.setenv("MCP_GC_REVENUECAT_WEBHOOK_SECRET", "provider-secret")
    db_path = tmp_path / "webhook-replay.db"
    payload = {
        "event": {
            "id": "rc-event-unique-123",
            "type": "CANCELLATION",
            "app_id": "com.example.app",
            "app_user_id": "subscriber-secret",
        }
    }
    headers = {"Authorization": "provider-secret"}

    with (
        patch("api_server.routes.webhooks.DEFAULT_DB_PATH", db_path),
        patch(
            "api_server.routes.webhooks.run_fcm_reengagement", new_callable=AsyncMock
        ) as reengage,
    ):
        first = client.post("/api/webhooks/revenuecat", json=payload, headers=headers)
        replay = client.post("/api/webhooks/revenuecat", json=payload, headers=headers)

    assert first.status_code == 200
    assert first.json()["status"] == "processing"
    assert replay.status_code == 200
    assert replay.json()["status"] == "duplicate"
    reengage.assert_awaited_once()

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT event_id_hash FROM webhook_event_receipts WHERE provider = 'revenuecat'"
        ).fetchone()
    assert row is not None
    assert row[0] != payload["event"]["id"]


def test_webhook_failures_back_off_and_expired_claims_are_retryable(tmp_path: Path) -> None:
    db_path = tmp_path / "webhook-state.db"
    state, first_token = claim_webhook_event("revenuecat", "event-retry", '{"event": {}}', db_path)
    assert state == "processing"
    assert first_token
    assert finish_webhook_event(
        "revenuecat",
        "event-retry",
        first_token,
        succeeded=False,
        error_safe="safe failure",
        db_path=db_path,
    )

    state, retry_token = claim_webhook_event("revenuecat", "event-retry", '{"event": {}}', db_path)
    assert state == "failed"
    assert retry_token is None

    due = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE webhook_event_receipts SET next_attempt_at = ? WHERE provider = ?",
            (due, "revenuecat"),
        )
    claim = claim_next_webhook_event("revenuecat", db_path)
    assert claim is not None
    retry_token = claim["claim_token"]
    assert retry_token != first_token

    expired = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE webhook_event_receipts SET claim_expires_at = ? WHERE provider = ?",
            (expired, "revenuecat"),
        )
    state, expired_retry_token = claim_webhook_event(
        "revenuecat", "event-retry", '{"event": {}}', db_path
    )
    assert state == "processing"
    assert expired_retry_token and expired_retry_token != retry_token
    assert finish_webhook_event(
        "revenuecat",
        "event-retry",
        expired_retry_token,
        succeeded=True,
        db_path=db_path,
    )
    assert claim_webhook_event("revenuecat", "event-retry", '{"event": {}}', db_path) == (
        "completed",
        None,
    )

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT state, attempts, last_error_safe FROM webhook_event_receipts"
        ).fetchone()
    assert row == ("completed", 3, None)


def test_legacy_webhook_receipts_migrate_to_completed(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy-webhook.db"
    event_id = "already-observed"
    event_hash = hashlib.sha256(event_id.encode()).hexdigest()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE webhook_event_receipts (
                provider TEXT NOT NULL,
                event_id_hash TEXT NOT NULL,
                received_at TEXT NOT NULL,
                PRIMARY KEY (provider, event_id_hash)
            );
            """
        )
        conn.execute(
            "INSERT INTO webhook_event_receipts VALUES (?, ?, ?);",
            ("revenuecat", event_hash, datetime.now(UTC).isoformat()),
        )

    assert claim_webhook_event("revenuecat", event_id, '{"event": {}}', db_path) == (
        "completed",
        None,
    )
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT state, next_attempt_at, max_attempts FROM webhook_event_receipts;"
        ).fetchone()
    assert row == ("completed", None, 5)


def test_delayed_poison_webhook_does_not_starve_newer_work_and_dead_letters(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "poison-webhook.db"
    _, poison_token = claim_webhook_event("revenuecat", "poison", "not-json", db_path)
    assert poison_token
    assert finish_webhook_event(
        "revenuecat", "poison", poison_token, succeeded=False, db_path=db_path
    )
    with sqlite3.connect(db_path) as conn:
        first_retry = conn.execute(
            "SELECT updated_at, next_attempt_at FROM webhook_event_receipts;"
        ).fetchone()
    first_delay = datetime.fromisoformat(first_retry[1]) - datetime.fromisoformat(first_retry[0])

    newer_hash = hashlib.sha256(b"newer").hexdigest()
    now = datetime.now(UTC).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO webhook_event_receipts (
                provider, event_id_hash, payload_json, state, received_at, updated_at
            ) VALUES ('revenuecat', ?, '{}', 'pending', ?, ?);
            """,
            (newer_hash, now, now),
        )
    newer_claim = claim_next_webhook_event("revenuecat", db_path)
    assert newer_claim is not None
    assert newer_claim["event_id_hash"] == newer_hash
    assert finish_webhook_receipt(
        "revenuecat",
        newer_hash,
        newer_claim["claim_token"],
        succeeded=True,
        db_path=db_path,
    )

    due = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE webhook_event_receipts SET max_attempts = 3, next_attempt_at = ?
            WHERE event_id_hash != ?;
            """,
            (due, newer_hash),
        )
    poison_claim = claim_next_webhook_event("revenuecat", db_path)
    assert poison_claim is not None
    assert finish_webhook_receipt(
        "revenuecat",
        poison_claim["event_id_hash"],
        poison_claim["claim_token"],
        succeeded=False,
        db_path=db_path,
    )
    with sqlite3.connect(db_path) as conn:
        second_retry = conn.execute(
            """
            SELECT updated_at, next_attempt_at FROM webhook_event_receipts
            WHERE event_id_hash != ?;
            """,
            (newer_hash,),
        ).fetchone()
        conn.execute(
            """
            UPDATE webhook_event_receipts SET next_attempt_at = ?
            WHERE event_id_hash != ?;
            """,
            (due, newer_hash),
        )
    second_delay = datetime.fromisoformat(second_retry[1]) - datetime.fromisoformat(second_retry[0])
    assert second_delay > first_delay

    final_claim = claim_next_webhook_event("revenuecat", db_path)
    assert final_claim is not None
    assert finish_webhook_receipt(
        "revenuecat",
        final_claim["event_id_hash"],
        final_claim["claim_token"],
        succeeded=False,
        db_path=db_path,
    )
    with sqlite3.connect(db_path) as conn:
        poison = conn.execute(
            "SELECT state, attempts, next_attempt_at FROM webhook_event_receipts WHERE event_id_hash != ?;",
            (newer_hash,),
        ).fetchone()
    assert poison == ("dead_letter", 3, None)


def test_read_only_blocks_admin_and_verified_webhook_without_persisting(
    monkeypatch: pytest.MonkeyPatch, client: TestClient, tmp_path: Path
) -> None:
    _enable_auth(monkeypatch)
    monkeypatch.setenv("MCP_GC_READ_ONLY", "1")
    monkeypatch.setenv("MCP_GC_REVENUECAT_WEBHOOK_SECRET", "provider-secret")
    admin_headers = {"Authorization": "Bearer admin-test-key"}
    assert client.post("/api/experiments/", json={}, headers=admin_headers).status_code == 403

    payload = {
        "event": {
            "id": "rc-event-read-only",
            "type": "CANCELLATION",
            "app_id": "com.example.app",
            "app_user_id": "subscriber-secret",
        }
    }
    provider_headers = {"Authorization": "provider-secret"}
    db_path = tmp_path / "read-only-webhook.db"
    with (
        patch("api_server.routes.webhooks.DEFAULT_DB_PATH", db_path),
        patch("api_server.routes.webhooks.run_fcm_reengagement", new_callable=AsyncMock),
    ):
        response = client.post("/api/webhooks/revenuecat", json=payload, headers=provider_headers)
    assert response.status_code == 403
    assert response.json()["detail"] == "API is in read-only mode; webhook processing is disabled"
    assert not db_path.exists()


@pytest.mark.asyncio
async def test_read_only_outbox_worker_does_not_claim_existing_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_GC_READ_ONLY", "1")
    sleep = AsyncMock(side_effect=[None, asyncio.CancelledError])
    claim = MagicMock()
    monkeypatch.setattr(webhooks.asyncio, "sleep", sleep)
    monkeypatch.setattr(webhooks, "claim_next_webhook_event", claim)

    with pytest.raises(asyncio.CancelledError):
        await webhooks.run_revenuecat_outbox_worker()

    claim.assert_not_called()


@pytest.mark.asyncio
async def test_reengagement_action_logs_redact_subscriber_identifier() -> None:
    credentials = SimpleNamespace(
        google_credentials_path=None,
        revenuecat_api_key=None,
        revenuecat_project_id=None,
        ga4_property_id=None,
        admob_account_id=None,
        gcs_play_console_bucket=None,
        gemini_api_key=None,
    )

    event = RevenueCatEvent(
        id="rc-event-redaction",
        type="CANCELLATION",
        app_id="com.example.app",
        app_user_id="subscriber-secret",
    )

    mock_client_instance = MagicMock()
    mock_client_instance.send_push_to_token.return_value = {"status": "success"}

    with (
        patch("api_server.routes.webhooks.get_app_credentials", return_value=credentials),
        patch("api_server.routes.webhooks.FCMClient", return_value=mock_client_instance),
        patch("api_server.routes.webhooks.log_db_action") as log_action,
    ):
        await run_fcm_reengagement(event)

    log_arguments = log_action.call_args.kwargs
    assert "subscriber-secret" not in log_arguments["arguments"]
    assert "subscriber-secret" not in log_arguments["reasoning"]
    assert "[REDACTED]" in log_arguments["arguments"]
    # The token is still passed to FCM (it's the send target, not a log field).
    mock_client_instance.send_push_to_token.assert_called_once()
    assert mock_client_instance.send_push_to_token.call_args[0][0] == "subscriber-secret"
