"""Regression tests for backend experiment execution and API lifecycle behavior."""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

import run_autonomous_loop
from api_server.main import app
from api_server.routes import experiments
from app_manager.credential_store import AppCredentials
from funnel_engine.db import get_db_experiments, init_db

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    "module_name",
    [
        "admob_mcp.server",
        "analytics_mcp.server",
        "app_store_mcp.server",
        "aso_keyword_mcp.server",
        "fcm_push_mcp.server",
        "revenuecat_mcp.server",
    ],
)
def test_http_mcp_entrypoints_configure_fastmcp_settings(
    module_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = importlib.import_module(module_name)
    run = MagicMock()
    monkeypatch.setattr(server.mcp, "run", run)
    monkeypatch.setattr(server.mcp.settings, "host", "127.0.0.1")
    monkeypatch.setattr(server.mcp.settings, "port", 8000)

    server.main(["--transport", "streamable-http", "--host", "127.0.0.2", "--port", "9123"])

    assert server.mcp.settings.host == "127.0.0.2"
    assert server.mcp.settings.port == 9123
    run.assert_called_once_with(transport="streamable-http")


def test_experiment_api_persists_execution_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "experiments.db"
    init_db(db_path)
    monkeypatch.setattr(experiments, "DEFAULT_DB_PATH", db_path)
    monkeypatch.setenv("MCP_GC_DEV_ALLOW_GENERIC_EXECUTABLE_PROPOSALS", "1")

    with TestClient(app) as client:
        response = client.post(
            "/api/experiments/",
            json={
                "app_package": "com.example.app",
                "experiment_type": "aso_metadata",
                "hypothesis": "A clearer title will improve conversion",
                "target_tool": "play_store/update_listing",
                "target_args": {"title": "Clear title"},
                "success_metric": "store_view_to_install_rate",
                "baseline_value": 0.2,
                "target_improvement_pct": 0.12,
                "rollback_degradation_pct": 0.08,
            },
        )
        assert response.status_code == 200
        experiment_id = response.json()["id"]

        approval = client.patch(
            f"/api/experiments/{experiment_id}",
            json={"status": "approved", "approved_via": "manual"},
        )
        assert approval.status_code == 422

        invalid = client.patch(f"/api/experiments/{experiment_id}", json={"status": "concluded"})
        assert invalid.status_code == 422
        missing = client.patch(
            "/api/experiments/missing",
            json={"status": "rejected", "reason": "not suitable"},
        )
        assert missing.status_code == 404

    stored = get_db_experiments(db_path)[0]
    assert stored["target_tool"] == "play_store/update_listing"
    assert stored["target_args"] == '{"title": "Clear title"}'
    assert stored["snapshot_before"] is None
    assert stored["target_improvement_pct"] == 0.12


def test_generic_executable_proposals_are_disabled_but_notes_are_allowed(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "generic-proposals.db"
    init_db(db_path)
    monkeypatch.setattr(experiments, "DEFAULT_DB_PATH", db_path)
    executable = {
        "app_package": "com.example.app",
        "experiment_type": "aso_metadata",
        "hypothesis": "Executable proposal",
        "success_metric": "store_view_to_install_rate",
        "target_tool": "play_store/update_listing",
        "target_args": {"title": "Unsafe"},
        "execution_mode": "manual",
    }
    note = {
        "app_package": "com.example.app",
        "experiment_type": "operator_note",
        "hypothesis": "Investigate conversion",
        "success_metric": "none",
    }

    with TestClient(app) as client:
        assert client.post("/api/experiments/", json=executable).status_code == 403
        created = client.post("/api/experiments/", json=note)

    assert created.status_code == 200
    stored = get_db_experiments(db_path)[0]
    assert stored["target_tool"] is None
    assert stored["execution_mode"] == "recommend_only"


@pytest.mark.asyncio
async def test_write_tool_uses_app_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    credentials = AppCredentials(
        package_name="com.example.app", google_credentials_path="/app/credentials.json"
    )
    monkeypatch.setattr(run_autonomous_loop, "get_app_credentials", lambda _package: credentials)
    play_client = MagicMock()
    play_client.update_listing.return_value.model_dump.return_value = {"success": True}
    client_factory = MagicMock(return_value=play_client)
    monkeypatch.setattr(run_autonomous_loop, "PlayStoreClient", client_factory)

    result = await run_autonomous_loop.execute_mcp_tool_call(
        "play_store/update_listing",
        {"packageName": "com.example.app", "language": "en-US", "title": "New title"},
        "com.example.app",
    )

    assert result == {"success": True}
    client_factory.assert_called_once_with(credentials_path="/app/credentials.json")


@pytest.mark.asyncio
async def test_safety_scan_uses_real_app_vitals(monkeypatch: pytest.MonkeyPatch) -> None:
    credentials = AppCredentials(
        package_name="com.example.app", google_credentials_path="/app/credentials.json"
    )
    monkeypatch.setattr(
        run_autonomous_loop,
        "get_apps_config",
        lambda: [{"package_name": "com.example.app", "display_name": "Example"}],
    )
    monkeypatch.setattr(run_autonomous_loop, "get_app_credentials", lambda _package: credentials)
    play_client = MagicMock()
    play_client.get_vitals_overview.return_value = SimpleNamespace(crash_rate=1.1, anr_rate=0.1)
    client_factory = MagicMock(return_value=play_client)
    monkeypatch.setattr(run_autonomous_loop, "PlayStoreClient", client_factory)
    log_action = MagicMock()
    monkeypatch.setattr(run_autonomous_loop, "log_db_action", log_action)
    set_brake = MagicMock()
    monkeypatch.setattr(run_autonomous_loop, "set_emergency_brake", set_brake)
    notify = AsyncMock(return_value=True)
    monkeypatch.setattr(run_autonomous_loop, "send_telegram_message", notify)

    await run_autonomous_loop.run_safety_scan()

    client_factory.assert_called_once_with(credentials_path="/app/credentials.json")
    log_action.assert_called_once()
    set_brake.assert_called_once()
    notify.assert_awaited_once()


@pytest.mark.asyncio
async def test_scheduler_only_automatically_rolls_back_explicit_rollback_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(run_autonomous_loop, "is_read_only", lambda: False)
    lifecycle = SimpleNamespace(retain=MagicMock(), rollback=AsyncMock())
    experiment = {
        "id": "exp-1",
        "execution_mode": "auto_low_risk",
        "approved_via": "auto_low_risk",
    }
    validation = {"valid": True, "effective_execution_mode": "auto_low_risk"}

    await run_autonomous_loop._apply_automatic_disposition(
        lifecycle,
        experiment,
        {"verdict": "loser", "reason": "Below target"},
        validation,
    )
    lifecycle.retain.assert_not_called()
    lifecycle.rollback.assert_not_awaited()

    await run_autonomous_loop._apply_automatic_disposition(
        lifecycle,
        experiment,
        {"verdict": "rollback", "reason": "Safety threshold crossed"},
        validation,
    )
    lifecycle.rollback.assert_awaited_once_with(
        "exp-1",
        actor="scheduler",
        reason="Automatic rollback disposition: Safety threshold crossed",
    )
