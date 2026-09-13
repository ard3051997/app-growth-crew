"""Security and failure-ordering regressions for backend operator APIs."""

from __future__ import annotations

import json
import stat
import zipfile
from io import BytesIO
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

import run_autonomous_loop
from api_server.main import app
from api_server.routes import apps, experiments, system
from app_manager.credential_store import AppCredentials
from app_manager.experiment_lifecycle import ExperimentLifecycle
from funnel_engine.db import (
    create_db_experiment,
    get_db_experiments,
    init_db,
    set_emergency_brake,
    update_db_experiment_status,
)
from mcp_gc_shared.write_guard import WriteBlockedError
from play_store_mcp.client import PlayStoreClient

if TYPE_CHECKING:
    from pathlib import Path


def _create_experiment(db_path: Path, baseline: float | None = 0.2) -> dict[str, object]:
    create_db_experiment(
        db_path=db_path,
        exp_id="exp-1",
        app_package="com.example.app",
        experiment_type="aso_metadata",
        hypothesis="Improve conversion",
        success_metric="store_view_to_install_rate",
        baseline_value=baseline,
        target_tool="play_store/update_listing",
        target_args=json.dumps({"title": "New title"}),
    )
    update_db_experiment_status(db_path, "exp-1", "approved")
    return get_db_experiments(db_path)[0]


def test_system_config_masks_secrets_and_preserves_masked_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "GEMINI_API_KEY=secret\nGOOGLE_APPLICATION_CREDENTIALS=/private/key.json\nGA4_PROPERTY_ID=123\n"
    )
    monkeypatch.setattr(system, "ENV_PATH", env_path)
    monkeypatch.setenv("MCP_GC_CONFIG_WRITES_ENABLED", "1")

    with TestClient(app) as client:
        response = client.get("/api/system/config")
        assert response.status_code == 200
        configs = response.json()["configs"]
        assert configs["GEMINI_API_KEY"] == system.MASKED_VALUE
        assert configs["GOOGLE_APPLICATION_CREDENTIALS"] == system.MASKED_VALUE
        assert configs["GA4_PROPERTY_ID"] == "123"

        update = client.post(
            "/api/system/config",
            json={"configs": {"GEMINI_API_KEY": system.MASKED_VALUE, "GA4_PROPERTY_ID": "456"}},
        )
        assert update.status_code == 200
        assert "GEMINI_API_KEY=secret" in env_path.read_text()
        assert "GA4_PROPERTY_ID=456" in env_path.read_text()

        rejected = client.post("/api/system/config", json={"configs": {"EVIL_KEY": "x"}})
        assert rejected.status_code == 422


def test_app_config_masks_paths_and_rejects_unknown_updates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_path = config_dir / "apps.json"
    config_path.write_text(
        json.dumps(
            {
                "apps": [
                    {
                        "package_name": "com.example.app",
                        "display_name": "Example",
                        "revenuecat_api_key": "secret",
                        "google_credentials_path": "/private/key.json",
                    }
                ]
            }
        )
    )
    monkeypatch.setattr(apps, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        apps, "_load_apps_config", lambda: json.loads(config_path.read_text())["apps"]
    )
    monkeypatch.setenv("MCP_GC_CONFIG_WRITES_ENABLED", "1")

    with TestClient(app) as client:
        response = client.get("/api/apps/com.example.app/config")
        assert response.json()["revenuecat_api_key"] == apps.MASKED_VALUE
        assert response.json()["google_credentials_path"] == apps.MASKED_VALUE

        update = client.put(
            "/api/apps/com.example.app/config",
            json={
                "fields": {
                    "display_name": "Renamed",
                    "revenuecat_api_key": apps.MASKED_VALUE,
                }
            },
        )
        assert update.status_code == 200
        stored = json.loads(config_path.read_text())["apps"][0]
        assert stored["display_name"] == "Renamed"
        assert stored["revenuecat_api_key"] == "secret"

        rejected = client.put(
            "/api/apps/com.example.app/config", json={"fields": {"package_name": "other"}}
        )
        assert rejected.status_code == 422


def test_config_writes_are_fail_closed_and_read_only_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TestClient(app) as client:
        assert client.post("/api/system/config", json={"configs": {}}).status_code == 403
        monkeypatch.setenv("MCP_GC_CONFIG_WRITES_ENABLED", "1")
        monkeypatch.setenv("MCP_GC_READ_ONLY", "1")
        assert client.post("/api/system/config", json={"configs": {}}).status_code == 403
        capabilities = client.get("/api/system/status").json()["capabilities"]
    assert capabilities == {"read_only": True, "config_writes": False}


def test_cors_defaults_to_local_frontend_origins() -> None:
    with TestClient(app) as client:
        local = client.options(
            "/api/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        remote = client.options(
            "/api/health",
            headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
        )
    assert local.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "access-control-allow-origin" not in remote.headers


@pytest.mark.asyncio
async def test_snapshot_is_persisted_before_external_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    experiment = _create_experiment(db_path)
    rollback_manager = MagicMock()
    rollback_manager.capture_snapshot = AsyncMock(return_value={"title": "Old title"})

    async def assert_persisted(*_args: object) -> dict[str, bool]:
        stored = get_db_experiments(db_path)[0]
        assert json.loads(stored["snapshot_before"])["title"] == "Old title"
        assert stored["status"] == "active"
        return {"success": True}

    monkeypatch.setattr(run_autonomous_loop, "execute_mcp_tool_call", assert_persisted)
    await run_autonomous_loop.deploy_approved_experiment(experiment, rollback_manager, db_path)
    assert get_db_experiments(db_path)[0]["status"] == "measuring"


@pytest.mark.asyncio
async def test_snapshot_persistence_failure_prevents_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    experiment = _create_experiment(db_path)
    rollback_manager = MagicMock()
    rollback_manager.capture_snapshot = AsyncMock(return_value={"title": "Old title"})
    execute = AsyncMock()
    monkeypatch.setattr(run_autonomous_loop, "persist_db_experiment_snapshot", lambda *_args: False)
    monkeypatch.setattr(run_autonomous_loop, "execute_mcp_tool_call", execute)

    with pytest.raises(RuntimeError, match="persist rollback snapshot"):
        await run_autonomous_loop.deploy_approved_experiment(experiment, rollback_manager, db_path)
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_post_write_bookkeeping_failure_does_not_requeue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    experiment = _create_experiment(db_path)
    rollback_manager = MagicMock()
    rollback_manager.capture_snapshot = AsyncMock(return_value={"title": "Old title"})
    monkeypatch.setattr(
        run_autonomous_loop, "execute_mcp_tool_call", AsyncMock(return_value={"success": True})
    )
    real_update = run_autonomous_loop.update_db_experiment_status

    def fail_measuring(*args: object, **kwargs: object) -> bool:
        status = kwargs.get("status") if kwargs else args[2]
        return False if status == "measuring" else real_update(*args, **kwargs)

    monkeypatch.setattr(run_autonomous_loop, "update_db_experiment_status", fail_measuring)
    with pytest.raises(run_autonomous_loop.PostWriteBookkeepingError):
        await run_autonomous_loop.deploy_approved_experiment(experiment, rollback_manager, db_path)
    assert get_db_experiments(db_path)[0]["status"] == "active"


@pytest.mark.asyncio
async def test_missing_baseline_and_emergency_brake_block_writes(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    no_baseline = _create_experiment(db_path, baseline=None)
    manager = MagicMock()
    manager.capture_snapshot = AsyncMock()
    with pytest.raises(RuntimeError, match="measured baseline"):
        await run_autonomous_loop.deploy_approved_experiment(no_baseline, manager, db_path)
    manager.capture_snapshot.assert_not_awaited()

    db_path_2 = tmp_path / "db2.sqlite"
    init_db(db_path_2)
    experiment = _create_experiment(db_path_2, baseline=0.0)
    set_emergency_brake(db_path_2, "com.example.app", "critical vitals")
    with pytest.raises(RuntimeError, match="Emergency brake"):
        await run_autonomous_loop.deploy_approved_experiment(experiment, manager, db_path_2)


@pytest.mark.asyncio
async def test_failed_rollback_does_not_transition_state(tmp_path: Path) -> None:
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    _create_experiment(db_path)
    update_db_experiment_status(
        db_path,
        "exp-1",
        "measuring",
        snapshot_before=json.dumps({"title": "Old", "language": "en-US"}),
        snapshot_after=json.dumps({"title": "New title", "language": "en-US"}),
    )
    experiment = get_db_experiments(db_path)[0]
    manager = MagicMock()
    manager.execute_rollback = AsyncMock(return_value=False)

    assert not await run_autonomous_loop.execute_experiment_rollback(
        experiment, manager, db_path=db_path
    )
    assert get_db_experiments(db_path)[0]["status"] == "measuring"


def test_manual_rollback_executes_before_transition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    _create_experiment(db_path)
    update_db_experiment_status(
        db_path,
        "exp-1",
        "measuring",
        snapshot_before=json.dumps({"title": "Old", "language": "en-US"}),
        snapshot_after=json.dumps({"title": "New title", "language": "en-US"}),
    )
    monkeypatch.setattr(experiments, "DEFAULT_DB_PATH", db_path)
    listing = {"language": "en-US", "title": "New title"}

    def write_listing(_package, args):
        listing["title"] = args["title"]
        return {"success": True}

    lifecycle = ExperimentLifecycle(
        db_path,
        rulebook_dir=tmp_path / "rulebooks",
        listing_reader=lambda *_args: dict(listing),
        listing_writer=write_listing,
    )
    monkeypatch.setattr(experiments, "_service", lambda: lifecycle)

    with TestClient(app) as client:
        failed = client.patch("/api/experiments/exp-1", json={"status": "rolled_back"})
        assert failed.status_code == 422
        assert get_db_experiments(db_path)[0]["status"] == "measuring"

        succeeded = client.post(
            "/api/experiments/exp-1/rollback",
            json={"reason": "restore known-good listing"},
        )
        assert succeeded.status_code == 200, succeeded.text
        assert get_db_experiments(db_path)[0]["status"] == "rolled_back"
        assert listing["title"] == "Old"


def test_safe_zip_extraction_rejects_traversal_and_links(tmp_path: Path) -> None:
    traversal = BytesIO()
    with zipfile.ZipFile(traversal, "w") as archive:
        archive.writestr("../escape.py", "bad")
    with pytest.raises(ValueError, match="escapes"):
        apps._safe_extract_zip(traversal.getvalue(), tmp_path)

    link = BytesIO()
    with zipfile.ZipFile(link, "w") as archive:
        info = zipfile.ZipInfo("link.py")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "target")
    with pytest.raises(ValueError, match="symbolic links"):
        apps._safe_extract_zip(link.getvalue(), tmp_path)


def test_safe_zip_extraction_enforces_compressed_and_expanded_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(apps, "MAX_ZIP_BYTES", 4)
    with pytest.raises(ValueError, match="compressed size"):
        apps._safe_extract_zip(b"12345", tmp_path)

    archive_bytes = BytesIO()
    with zipfile.ZipFile(archive_bytes, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("large.py", "x" * 20)
    monkeypatch.setattr(apps, "MAX_ZIP_BYTES", 1_000)
    monkeypatch.setattr(apps, "MAX_ZIP_MEMBER_BYTES", 10)
    with pytest.raises(ValueError, match="member exceeds"):
        apps._safe_extract_zip(archive_bytes.getvalue(), tmp_path)


def test_period_specific_requests_do_not_use_30d_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        apps,
        "get_latest_app_snapshot",
        lambda *_args: {
            "raw_funnel_json": '{"cached": true}',
            "raw_revenue_json": '{"cached": true, "revenuecat": {"revenue": 10}}',
        },
    )
    funnel = MagicMock(return_value='{"period": "7d"}')
    monkeypatch.setattr(apps, "run_funnel_analysis", funnel)
    monkeypatch.setattr(
        apps,
        "get_app_credentials",
        lambda _package: AppCredentials(package_name="com.finance.loan.emicalculator"),
    )

    with TestClient(app) as client:
        funnel_response = client.get(
            "/api/apps/com.finance.loan.emicalculator/funnel?period=7d"
        ).json()
        assert funnel_response["period"] == "7d"
        assert funnel_response["provenance"]["source"] == "funnel_engine_live"
        revenue = client.get("/api/apps/com.finance.loan.emicalculator/revenue?period=7d").json()
    assert "cached" not in revenue


def test_portfolio_rejects_incomplete_7d_revenue_components() -> None:
    with TestClient(app) as client:
        portfolio_response = client.get("/api/portfolio/?period=7d")
        summary_response = client.get("/api/portfolio/summary?period=7d")

    assert portfolio_response.status_code == 422
    assert summary_response.status_code == 422


def test_play_store_listing_write_guard_runs_before_client_initialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_GC_READ_ONLY", "1")
    client = PlayStoreClient(credentials_path="/missing.json")

    with pytest.raises(WriteBlockedError, match="MCP_GC_READ_ONLY"):
        client.update_listing("com.example.app", "en-US", title="Blocked")
