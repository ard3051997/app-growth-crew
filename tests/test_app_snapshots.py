"""Tests for SQLite cached metrics snapshot operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from funnel_engine.db import (
    get_all_latest_snapshots,
    get_app_snapshot_history,
    get_latest_app_snapshot,
    init_db,
    save_app_metrics_snapshot,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Fixture to initialize a temporary test database."""
    test_db = tmp_path / "test_performance.db"
    init_db(test_db)
    return test_db


def test_save_and_retrieve_snapshot(db_path: Path) -> None:
    # Save a metrics snapshot
    metrics: dict[str, Any] = {
        "funnel_health_score": 85.5,
        "top_leak_name": "Store CVR",
        "top_leak_value": 0.18,
        "top_leak_benchmark": 0.25,
        "mrr": 500.0,
        "mrr_change_pct": 2.5,
        "ad_revenue_30d": 1200.0,
        "rc_revenue_30d": 400.0,
        "total_revenue_30d": 1600.0,
        "installs_7d": "[100, 110, 120]",
        "active_users_30d": 5000,
        "d1_retention": 0.45,
        "d7_retention": 0.20,
        "raw_funnel_json": '{"status": "ok"}',
        "raw_revenue_json": '{"revenue": 1600}',
    }

    save_app_metrics_snapshot(
        db_path=db_path,
        package_name="com.test.app",
        snapshot_date="2026-06-20",
        metrics=metrics,
    )

    # Retrieve and check
    snap = get_latest_app_snapshot(db_path, "com.test.app")
    assert snap is not None
    assert snap["package_name"] == "com.test.app"
    assert snap["snapshot_date"] == "2026-06-20"
    assert snap["funnel_health_score"] == 85.5
    assert snap["mrr"] == 500.0
    assert snap["total_revenue_30d"] == 1600.0
    assert snap["active_users_30d"] == 5000
    assert snap["raw_funnel_json"] == '{"status": "ok"}'


def test_save_snapshot_overwrites(db_path: Path) -> None:
    metrics1 = {"funnel_health_score": 80.0}
    metrics2 = {"funnel_health_score": 90.0}

    # Save twice for same package and date (should overwrite due to UNIQUE constraint)
    save_app_metrics_snapshot(db_path, "com.test.app", "2026-06-20", metrics1)
    save_app_metrics_snapshot(db_path, "com.test.app", "2026-06-20", metrics2)

    snap = get_latest_app_snapshot(db_path, "com.test.app")
    assert snap is not None
    assert snap["funnel_health_score"] == 90.0


def test_get_all_latest_snapshots(db_path: Path) -> None:
    # Save multiple dates for App A
    save_app_metrics_snapshot(db_path, "com.app.a", "2026-06-19", {"funnel_health_score": 70.0})
    save_app_metrics_snapshot(db_path, "com.app.a", "2026-06-20", {"funnel_health_score": 75.0})

    # Save single date for App B
    save_app_metrics_snapshot(db_path, "com.app.b", "2026-06-20", {"funnel_health_score": 85.0})

    # Retrieve all latest
    snapshots = get_all_latest_snapshots(db_path)
    assert len(snapshots) == 2

    snap_map = {s["package_name"]: s for s in snapshots}
    assert snap_map["com.app.a"]["snapshot_date"] == "2026-06-20"
    assert snap_map["com.app.a"]["funnel_health_score"] == 75.0
    assert snap_map["com.app.b"]["snapshot_date"] == "2026-06-20"
    assert snap_map["com.app.b"]["funnel_health_score"] == 85.0


def test_get_app_snapshot_history(db_path: Path) -> None:
    # Insert a history of snapshots
    save_app_metrics_snapshot(db_path, "com.test.app", "2026-06-18", {"mrr": 400.0})
    save_app_metrics_snapshot(db_path, "com.test.app", "2026-06-19", {"mrr": 410.0})
    save_app_metrics_snapshot(db_path, "com.test.app", "2026-06-20", {"mrr": 420.0})

    history = get_app_snapshot_history(db_path, "com.test.app", days=3)
    assert len(history) == 3
    assert history[0]["mrr"] == 400.0
    assert history[-1]["mrr"] == 420.0
