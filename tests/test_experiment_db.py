import os
import tempfile
from pathlib import Path

import pytest

from funnel_engine.db import (
    add_db_observation,
    create_db_experiment,
    get_db_actions,
    get_db_connection,
    get_db_experiments,
    get_db_observations,
    init_db,
    insert_db_observation_if_non_overlapping,
    log_db_action,
    update_db_experiment_status,
)


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp()
    try:
        init_db(path)
        yield Path(path)
    finally:
        os.close(fd)
        Path(path).unlink()


def test_db_initialization(temp_db):
    conn = get_db_connection(temp_db)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row["name"] for row in cursor.fetchall()]
    conn.close()

    assert "experiments" in tables
    assert "experiment_observations" in tables
    assert "action_log" in tables
    assert "system_confidence" in tables


def test_insert_observation_accepts_null_visitors_and_installs_for_rank_metrics(temp_db):
    create_db_experiment(
        db_path=temp_db,
        exp_id="rank-exp-1",
        app_package="com.example.iosapp",
        experiment_type="aso_metadata",
        hypothesis="Rank test",
        success_metric="keyword_rank",
    )
    result = insert_db_observation_if_non_overlapping(
        temp_db,
        "rank-exp-1",
        "2026-08-01",
        138.0,
        None,
        locale="en-US",
        period_start="2026-08-01",
        period_end="2026-08-01",
        source="app_store_search_api",
    )
    assert result == "inserted"

    rows = get_db_observations(temp_db, "rank-exp-1")
    assert len(rows) == 1
    assert rows[0]["visitors"] is None
    assert rows[0]["installs"] is None
    assert rows[0]["metric_value"] == 138.0

    # Same date, different rank -> conflict, not a silent duplicate
    conflict = insert_db_observation_if_non_overlapping(
        temp_db,
        "rank-exp-1",
        "2026-08-01",
        90.0,
        None,
        locale="en-US",
        period_start="2026-08-01",
        period_end="2026-08-01",
        source="app_store_search_api",
    )
    assert conflict == "conflict"

    # Same date, same rank -> idempotent duplicate
    duplicate = insert_db_observation_if_non_overlapping(
        temp_db,
        "rank-exp-1",
        "2026-08-01",
        138.0,
        None,
        locale="en-US",
        period_start="2026-08-01",
        period_end="2026-08-01",
        source="app_store_search_api",
    )
    assert duplicate == "duplicate"


def test_experiment_crud(temp_db):
    # Create
    create_db_experiment(
        db_path=temp_db,
        exp_id="test-exp-123",
        app_package="com.example.test",
        experiment_type="aso_metadata",
        hypothesis="Test hypothesis",
        success_metric="store_view_to_install_rate",
        baseline_value=0.15,
        target_value=0.20,
        rollback_threshold=0.10,
        snapshot_before='{"title": "Old Title"}',
        created_by="manual",
        target_tool="play_store/update_listing",
        target_args='{"title": "New Title"}',
        target_improvement_pct=0.1,
        rollback_degradation_pct=0.15,
    )

    # Retrieve
    exps = get_db_experiments(temp_db)
    assert len(exps) == 1
    assert exps[0]["id"] == "test-exp-123"
    assert exps[0]["status"] == "proposed"
    assert exps[0]["created_by"] == "manual"
    assert exps[0]["target_tool"] == "play_store/update_listing"
    assert exps[0]["target_args"] == '{"title": "New Title"}'

    # Update Status
    update_db_experiment_status(db_path=temp_db, exp_id="test-exp-123", status="active")
    exps = get_db_experiments(temp_db, status="active")
    assert len(exps) == 1
    assert exps[0]["started_at"] is not None

    # Update status to concluded with results
    update_db_experiment_status(
        db_path=temp_db,
        exp_id="test-exp-123",
        status="concluded",
        result_value=0.22,
        result_verdict="winner",
        confidence=0.96,
        snapshot_after='{"title": "New Title"}',
        approved_via="manual",
    )
    exps = get_db_experiments(temp_db, status="concluded")
    assert len(exps) == 1
    assert exps[0]["result_value"] == 0.22
    assert exps[0]["result_verdict"] == "winner"
    assert exps[0]["confidence"] == 0.96
    assert exps[0]["snapshot_after"] == '{"title": "New Title"}'


def test_observations(temp_db):
    # Insert experiment
    create_db_experiment(
        db_path=temp_db,
        exp_id="test-exp-obs",
        app_package="com.example.test",
        experiment_type="paywall_variant",
        hypothesis="Test hypothesis",
        success_metric="trial_to_paid_conversion",
    )

    # Add observations
    add_db_observation(temp_db, "test-exp-obs", "2026-06-15", 0.05, '{"installs": 100}')
    add_db_observation(temp_db, "test-exp-obs", "2026-06-16", 0.06, '{"installs": 120}')

    # Retrieve
    obs = get_db_observations(temp_db, "test-exp-obs")
    assert len(obs) == 2
    assert obs[0]["observed_at"] == "2026-06-15"
    assert obs[0]["metric_value"] == 0.05
    assert obs[1]["observed_at"] == "2026-06-16"
    assert obs[1]["metric_value"] == 0.06


def test_action_log(temp_db):
    # Log action
    log_db_action(
        db_path=temp_db,
        action_type="mcp_tool_call",
        app_package="com.example.test",
        tool_name="update_listing",
        arguments='{"title": "Test app"}',
        result="success",
        reasoning="Test reasoning",
    )

    # Retrieve
    actions = get_db_actions(temp_db)
    assert len(actions) == 1
    assert actions[0]["action_type"] == "mcp_tool_call"
    assert actions[0]["tool_name"] == "update_listing"
    assert actions[0]["result"] == "success"
    assert actions[0]["reasoning"] == "Test reasoning"
