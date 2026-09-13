"""Operational truth tests for connector state, scheduling, and snapshots."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from api_server.routes import system
from app_manager.credential_store import AppCredentials
from funnel_engine.db import (
    SCHEMA_VERSION,
    finish_sync_run,
    get_db_connection,
    get_latest_app_snapshot,
    get_source_watermarks,
    init_db,
    safe_sync_error,
    start_sync_run,
)
from funnel_engine_mcp import server as funnel_server


def test_additive_migration_and_connection_pragmas(tmp_path) -> None:
    db_path = tmp_path / "legacy.db"
    legacy = sqlite3.connect(db_path)
    legacy.execute(
        """
        CREATE TABLE app_metrics_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            package_name TEXT NOT NULL,
            snapshot_date TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(package_name, snapshot_date)
        );
        """
    )
    legacy.commit()
    legacy.close()

    init_db(db_path)

    conn = get_db_connection(db_path)
    try:
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table';")
        }
        snapshot_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(app_metrics_snapshots);")
        }
        assert {
            "schema_migrations",
            "sync_runs",
            "source_watermarks",
            "scheduler_heartbeat",
        } <= tables
        assert {"source_status_json", "data_as_of", "is_partial"} <= snapshot_columns
        assert conn.execute("PRAGMA foreign_keys;").fetchone()[0] == 1
        assert conn.execute("PRAGMA journal_mode;").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA busy_timeout;").fetchone()[0] == 5_000
        assert conn.execute("PRAGMA user_version;").fetchone()[0] == SCHEMA_VERSION
    finally:
        conn.close()


def test_sync_run_lifecycle_preserves_last_success_and_safe_errors(tmp_path) -> None:
    db_path = tmp_path / "sync.db"
    init_db(db_path)
    success_id = start_sync_run(db_path, "storefront", "com.example.app")
    finish_sync_run(
        db_path,
        success_id,
        "success",
        record_count=12,
        period_start="2026-06-01",
        period_end="2026-06-30",
    )
    first = get_source_watermarks(db_path, "com.example.app")[0]

    failure_id = start_sync_run(db_path, "storefront", "com.example.app")
    error = safe_sync_error(RuntimeError("secret-token-value"), "Storefront unavailable")
    finish_sync_run(db_path, failure_id, "failure", error_safe=error)
    latest = get_source_watermarks(db_path, "com.example.app")[0]

    assert latest["last_status"] == "failure"
    assert latest["last_success_at"] == first["last_success_at"]
    assert latest["error_safe"] == "Storefront unavailable (RuntimeError)"
    assert "secret-token-value" not in latest["error_safe"]


def test_older_sync_completion_cannot_overwrite_current_watermark(tmp_path) -> None:
    db_path = tmp_path / "sync-race.db"
    init_db(db_path)
    older = start_sync_run(db_path, "storefront", "com.example.app")
    current = start_sync_run(db_path, "storefront", "com.example.app")

    finish_sync_run(db_path, older, "success", record_count=99)
    watermark = get_source_watermarks(db_path, "com.example.app")[0]
    assert watermark["last_run_id"] == current
    assert watermark["last_status"] == "running"
    assert watermark["record_count"] == 0

    finish_sync_run(db_path, current, "failure", error_safe="Current run failed")
    watermark = get_source_watermarks(db_path, "com.example.app")[0]
    assert watermark["last_status"] == "failure"
    assert watermark["record_count"] == 0


@pytest.mark.asyncio
async def test_malformed_storefront_files_fail_without_historical_coverage(
    tmp_path, monkeypatch
) -> None:
    from app_manager import storefront_analyst

    db_path = tmp_path / "storefront-malformed.db"
    export_path = tmp_path / "storefront.json"
    monkeypatch.setattr(
        storefront_analyst,
        "_storefront_config",
        lambda _package: SimpleNamespace(gcs_play_console_bucket="bucket"),
    )
    gcs = SimpleNamespace(read_blob_content=lambda *_args: "not,a,valid,report\n")
    monkeypatch.setattr(storefront_analyst, "_get_gcs_client", lambda _config: gcs)

    result = await storefront_analyst.ingest_latest_month(
        "com.example.app", db_path=db_path, export_path=export_path
    )

    assert result["status"] == "failure"
    assert result["records_inserted"] == 0
    assert result["period_start"] is None
    assert result["period_end"] is None
    watermark = get_source_watermarks(db_path, "com.example.app")[0]
    assert watermark["last_status"] == "failure"
    assert watermark["period_start"] is None


@pytest.mark.asyncio
async def test_storefront_run_coverage_uses_only_dates_from_persisted_rows(
    tmp_path, monkeypatch
) -> None:
    from app_manager import storefront_analyst

    db_path = tmp_path / "storefront-coverage.db"
    monkeypatch.setattr(
        storefront_analyst,
        "_storefront_config",
        lambda _package: SimpleNamespace(gcs_play_console_bucket="bucket"),
    )

    def report(_bucket, blob_name):
        if blob_name.endswith("_country.csv"):
            return (
                "Date,Country,Store Listing Visitors,Store Listing Acquisitions\n"
                "20260601,IN,100,20\n"
                "2026-01-01,US,invalid,5\n"
            )
        return (
            "Date,Traffic Source,Store Listing Visitors,Store Listing Acquisitions\n"
            "2026-06-02,Search,80,10\n"
            "not-a-date,Explore,30,2\n"
        )

    monkeypatch.setattr(
        storefront_analyst,
        "_get_gcs_client",
        lambda _config: SimpleNamespace(read_blob_content=report),
    )

    result = await storefront_analyst.ingest_latest_month(
        "com.example.app",
        db_path=db_path,
        export_path=tmp_path / "storefront.json",
    )

    assert result["status"] == "success"
    assert result["period_start"] == "2026-06-01"
    assert result["period_end"] == "2026-06-02"


def test_system_status_marks_old_observed_source_stale(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "status.db"
    init_db(db_path)
    run_id = start_sync_run(db_path, "funnel", "com.example.app")
    finish_sync_run(db_path, run_id, "success", record_count=8)
    old = (datetime.now(UTC) - timedelta(days=3)).isoformat()
    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                UPDATE source_watermarks
                SET last_started_at = ?, last_completed_at = ?, last_success_at = ?
                WHERE source = 'funnel';
                """,
                (old, old, old),
            )
    finally:
        conn.close()
    monkeypatch.setattr(system, "DEFAULT_DB_PATH", db_path)

    status = system.get_system_status()

    assert status["services"]["funnel_engine"] == "stale"
    assert status["source_runs"][0]["state"] == "stale"
    assert status["scheduler"]["state"] == "unavailable"


def test_system_status_newer_failure_masks_older_service_success(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "status-latest.db"
    init_db(db_path)
    successful = start_sync_run(db_path, "storefront", "com.example.app")
    finish_sync_run(db_path, successful, "success", record_count=10)
    failed = start_sync_run(db_path, "storefront_backfill", "com.example.app")
    finish_sync_run(db_path, failed, "failure", error_safe="Current import failed")
    monkeypatch.setattr(system, "DEFAULT_DB_PATH", db_path)

    status = system.get_system_status()

    assert status["services"]["play_store"] == "unavailable"


def test_funnel_without_analytics_is_labeled_unavailable(monkeypatch) -> None:
    monkeypatch.delenv("MCP_GC_DEMO_MODE", raising=False)
    monkeypatch.setattr(
        "app_manager.credential_store.get_app_credentials",
        lambda package: AppCredentials(package_name=package),
    )
    analytics = MagicMock()
    monkeypatch.setattr(funnel_server, "AnalyticsClient", analytics)

    result = json.loads(funnel_server.run_funnel_analysis("com.example.app"))

    assert result["status"] == "unavailable"
    assert result["funnel_health_score"] is None
    assert result["all_steps"] == []
    assert result["unavailable_sources"] == ["analytics"]
    analytics.assert_not_called()


@pytest.mark.asyncio
async def test_critical_funnel_failure_preserves_existing_snapshot(tmp_path, monkeypatch) -> None:
    import run_autonomous_loop
    from app_manager import storefront_analyst

    db_path = tmp_path / "snapshots.db"
    init_db(db_path)
    monkeypatch.setattr(run_autonomous_loop, "DEFAULT_DB_PATH", db_path)
    monkeypatch.setattr(
        run_autonomous_loop,
        "get_apps_config",
        lambda: [{"package_name": "com.example.app", "app_category": "utilities"}],
    )
    monkeypatch.setattr(
        run_autonomous_loop,
        "get_app_credentials",
        lambda _package: SimpleNamespace(get_available_services=list),
    )

    async def ingest(*_args, **_kwargs):
        return {"status": "success"}

    monkeypatch.setattr(storefront_analyst, "ingest_latest_month", ingest)
    monkeypatch.setattr(
        run_autonomous_loop,
        "run_funnel_analysis",
        lambda **_kwargs: json.dumps(
            {"status": "partial", "funnel_health_score": None, "all_steps": []}
        ),
    )
    save = MagicMock()
    monkeypatch.setattr(run_autonomous_loop, "save_app_metrics_snapshot", save)

    await run_autonomous_loop.collect_app_snapshots()

    save.assert_not_called()


@pytest.mark.asyncio
async def test_snapshot_extracts_real_top_leak_fields(tmp_path, monkeypatch) -> None:
    import run_autonomous_loop
    from app_manager import storefront_analyst

    db_path = tmp_path / "top-leak.db"
    init_db(db_path)
    monkeypatch.setattr(run_autonomous_loop, "DEFAULT_DB_PATH", db_path)
    monkeypatch.setattr(
        run_autonomous_loop,
        "get_apps_config",
        lambda: [{"package_name": "com.example.app", "app_category": "utilities"}],
    )
    credentials = SimpleNamespace(
        get_available_services=list,
        has_admob=lambda: False,
        has_revenuecat=lambda: False,
        has_analytics=lambda: False,
        has_app_store_connect=lambda: False,
        has_google_ads=lambda: False,
        gcs_play_console_bucket=None,
        google_credentials_path=None,
        google_ads_customer_id=None,
    )
    monkeypatch.setattr(run_autonomous_loop, "get_app_credentials", lambda _package: credentials)

    async def ingest(*_args, **_kwargs):
        return {"status": "success"}

    monkeypatch.setattr(storefront_analyst, "ingest_latest_month", ingest)
    monkeypatch.setattr(
        run_autonomous_loop,
        "run_funnel_analysis",
        lambda **_kwargs: json.dumps(
            {
                "status": "success",
                "funnel_health_score": 72,
                "all_steps": [{"name": "Store View -> Install"}],
                "leaks": [
                    {
                        "name": "Store View -> Install",
                        "conversion_rate": 0.18,
                        "benchmark_rate": 0.33,
                    }
                ],
            }
        ),
    )
    save = MagicMock()
    monkeypatch.setattr(run_autonomous_loop, "save_app_metrics_snapshot", save)

    await run_autonomous_loop.collect_app_snapshots()

    metrics = save.call_args.kwargs["metrics"]
    assert metrics["top_leak_name"] == "Store View -> Install"
    assert metrics["top_leak_value"] == 0.18
    assert metrics["top_leak_benchmark"] == 0.33


@pytest.mark.asyncio
async def test_carried_forward_source_preserves_original_timestamp(tmp_path, monkeypatch) -> None:
    import run_autonomous_loop
    from app_manager import storefront_analyst

    db_path = tmp_path / "carried-forward.db"
    init_db(db_path)
    monkeypatch.setattr(run_autonomous_loop, "DEFAULT_DB_PATH", db_path)
    monkeypatch.setattr(
        run_autonomous_loop,
        "get_apps_config",
        lambda: [{"package_name": "com.example.app", "app_category": "utilities"}],
    )
    credentials = SimpleNamespace(
        get_available_services=list,
        has_admob=lambda: True,
        has_revenuecat=lambda: False,
        has_analytics=lambda: False,
        has_app_store_connect=lambda: False,
        has_google_ads=lambda: False,
        gcs_play_console_bucket=None,
        google_credentials_path=None,
        google_ads_customer_id=None,
        admob_account_id="pub-1",
    )
    monkeypatch.setattr(run_autonomous_loop, "get_app_credentials", lambda _package: credentials)

    async def ingest(*_args, **_kwargs):
        return {"status": "success"}

    monkeypatch.setattr(storefront_analyst, "ingest_latest_month", ingest)
    monkeypatch.setattr(
        run_autonomous_loop,
        "run_funnel_analysis",
        lambda **_kwargs: json.dumps(
            {"status": "success", "funnel_health_score": 80, "all_steps": [{}], "leaks": []}
        ),
    )
    admob_results = iter([{"ad_revenue_30d": 12.5}, None])
    monkeypatch.setattr(funnel_server, "_fetch_admob_metrics", lambda *_args: next(admob_results))

    await run_autonomous_loop.collect_app_snapshots()
    first = get_latest_app_snapshot(db_path, "com.example.app")
    assert first is not None
    first_sources = json.loads(first["source_status_json"])
    first_timestamp = first_sources["admob"]["captured_at"]

    await run_autonomous_loop.collect_app_snapshots()
    second = get_latest_app_snapshot(db_path, "com.example.app")
    assert second is not None
    second_sources = json.loads(second["source_status_json"])
    assert second["ad_revenue_30d"] == 12.5
    assert second_sources["admob"]["status"] == "carried_forward"
    assert second_sources["admob"]["captured_at"] == first_timestamp
    assert second_sources["admob"]["original_captured_at"] == first_timestamp
    assert second_sources["admob"]["carried_forward"] is True
    assert second_sources["ad_revenue"]["original_captured_at"] == first_timestamp


def test_portfolio_revenue_provenance_does_not_refresh_carried_values(monkeypatch) -> None:
    from api_server.routes import portfolio

    snapshot_time = "2026-07-20T08:00:00+00:00"
    original_ad_capture = "2026-07-18T08:00:00+00:00"
    snapshot = {
        "package_name": "com.example.app",
        "snapshot_date": "2026-07-20",
        "data_as_of": snapshot_time,
        "ad_revenue_30d": 12.5,
        "rc_revenue_30d": 7.0,
        "total_revenue_30d": 19.5,
        "mrr": 3.0,
        "source_status_json": json.dumps(
            {
                "ad_revenue": {
                    "source": "admob",
                    "status": "carried_forward",
                    "captured_at": original_ad_capture,
                    "original_captured_at": original_ad_capture,
                    "carried_forward": True,
                },
                "subscription_revenue": {
                    "source": "revenuecat",
                    "status": "success",
                    "captured_at": snapshot_time,
                    "original_captured_at": snapshot_time,
                    "carried_forward": False,
                },
                "mrr": {
                    "source": "revenuecat",
                    "status": "success",
                    "captured_at": snapshot_time,
                    "original_captured_at": snapshot_time,
                    "carried_forward": False,
                },
                "iap_revenue": {
                    "source": "gcs_revenue",
                    "status": "success",
                    "captured_at": snapshot_time,
                    "original_captured_at": snapshot_time,
                    "carried_forward": False,
                },
            }
        ),
        "raw_revenue_json": json.dumps(
            {
                "metric_values": {
                    "subscription_revenue_30d": 4.0,
                    "iap_revenue_30d": 3.0,
                }
            }
        ),
    }
    monkeypatch.setattr(
        portfolio,
        "get_apps_config",
        lambda: [{"package_name": "com.example.app", "display_name": "Example"}],
    )
    monkeypatch.setattr(portfolio, "get_db_experiments", lambda *_args: [])
    monkeypatch.setattr(portfolio, "get_all_latest_snapshots", lambda *_args: [snapshot])

    app = portfolio.get_portfolio()["apps"][0]

    assert app["freshness"] == snapshot_time
    assert app["subscription_revenue_30d"] == 4.0
    assert app["iap_revenue_30d"] == 3.0
    assert app["revenue_provenance"]["ad"]["carried_forward"] is True
    assert app["revenue_provenance"]["ad"]["captured_at"] == original_ad_capture
    assert app["revenue_provenance"]["ad"]["captured_at"] != app["freshness"]
    assert app["revenue_provenance"]["iap"]["source"] == "gcs_revenue"
