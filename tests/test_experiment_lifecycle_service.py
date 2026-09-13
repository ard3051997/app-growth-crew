"""Focused lifecycle tests using a temporary database and in-memory Play listing."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient

from api_server.main import app
from api_server.routes import actions, experiments
from app_manager.experiment_lifecycle import (
    RANK_NOT_FOUND_SENTINEL,
    ExperimentLifecycle,
    LifecycleConflictError,
    evaluate_keyword_rank_change,
    evaluate_two_proportion_conversion,
)
from app_manager.experiment_validation import validate_experiment
from funnel_engine.db import (
    create_db_experiment,
    get_db_experiment,
    init_db,
    log_db_action,
    set_emergency_brake,
    update_db_experiment_fields,
)

if TYPE_CHECKING:
    from pathlib import Path


PACKAGE = "com.example.app"
NOW = datetime(2026, 7, 20, 12, tzinfo=UTC)


def _evidence(*, visitors: int = 10_000, installs: int = 2_000) -> dict[str, Any]:
    return {
        "baseline": {
            "metric": "store_view_to_install_rate",
            "locale": "en-US",
            "visitors": visitors,
            "installs": installs,
            "measured_at": NOW.isoformat(),
            "period_end": NOW.date().isoformat(),
            "source": "play_console_daily_country",
        }
    }


def _create(db_path: Path, experiment_id: str = "exp-1") -> None:
    create_db_experiment(
        db_path,
        experiment_id,
        PACKAGE,
        "aso_metadata",
        "A clearer title improves listing conversion",
        "store_view_to_install_rate",
        min_observation_days=1,
        max_observation_days=7,
        target_tool="play_store/update_listing",
        target_args=json.dumps(
            {
                "packageName": PACKAGE,
                "language": "en-US",
                "title": "Better App Title",
            }
        ),
        target_improvement_pct=0.10,
        rollback_degradation_pct=0.15,
        evidence_json=json.dumps(_evidence()),
        execution_mode="manual",
    )


def _rank_evidence(*, keyword: str = "pomodoro", rank: int | None = 138) -> dict[str, Any]:
    return {
        "baseline": {
            "metric": "keyword_rank",
            "keyword": keyword,
            "rank": rank,
            "locale": "en-US",
            "measured_at": NOW.isoformat(),
            "source": "app_store_search_api",
        }
    }


def _create_rank(
    db_path: Path, experiment_id: str = "exp-rank-1", *, rank: int | None = 138
) -> None:
    create_db_experiment(
        db_path,
        experiment_id,
        PACKAGE,
        "aso_metadata",
        "Adding 'pomodoro' will improve App Store search rank",
        "keyword_rank",
        min_observation_days=1,
        max_observation_days=7,
        target_tool="app_store_connect/update_listing",
        target_args=json.dumps(
            {
                "packageName": PACKAGE,
                "language": "en-US",
                "title": "Pomodori - Pomodoro Timer",
            }
        ),
        target_improvement_pct=0.10,
        rollback_degradation_pct=0.15,
        evidence_json=json.dumps(_rank_evidence(rank=rank)),
        execution_mode="manual",
    )


def _proposal(mode: str) -> dict[str, Any]:
    evidence = _evidence()
    evidence.update(
        {
            "current_listing": {
                "title": "Old App Title",
                "short_description": "Old short description",
                "full_description": "Old full description",
                "language": "en-US",
                "provenance": {
                    "source": "google_play_developer_api",
                    "live": True,
                    "retrieved_at": NOW.isoformat(),
                },
            },
            "proposed_listing": {
                "title": "Better App Title",
                "short_description": "Old short description",
                "full_description": "Old full description",
                "language": "en-US",
                "provenance": {
                    "source": "operator",
                    "live": False,
                    "retrieved_at": NOW.isoformat(),
                },
            },
            "rulebook": {},
            "rulebook_source": "rulebooks/com.example.app.yaml",
        }
    )
    return {
        "app_package": PACKAGE,
        "experiment_type": "aso_metadata",
        "hypothesis": "A clearer title improves listing conversion",
        "success_metric": "store_view_to_install_rate",
        "target_tool": "play_store/update_listing",
        "target_args": {
            "packageName": PACKAGE,
            "language": "en-US",
            "title": "Better App Title",
            "shortDescription": "Old short description",
            "fullDescription": "Old full description",
        },
        "baseline_value": 0.2,
        "target_value": 0.22,
        "target_improvement_pct": 0.1,
        "min_observation_days": 1,
        "max_observation_days": 7,
        "rollback_degradation_pct": 0.15,
        "execution_mode": mode,
        "evidence": evidence,
        "created_by": "operator",
    }


def test_pure_validator_enforces_policy_fresh_counts_and_rulebook() -> None:
    experiment = {
        "id": "exp-1",
        "app_package": PACKAGE,
        "experiment_type": "aso_metadata",
        "target_tool": "play_store/update_listing",
        "target_args": {
            "packageName": PACKAGE,
            "language": "en-US",
            "title": "Better App Title",
        },
        "success_metric": "store_view_to_install_rate",
        "execution_mode": "auto_low_risk",
    }
    result = validate_experiment(
        experiment,
        evidence=_evidence(),
        rulebook={"metadata_constraints": {"title": {"required_keywords": ["Missing"]}}},
        system_max_execution_mode="manual",
        now=NOW,
    )

    assert not result["valid"]
    assert {error["code"] for error in result["errors"]} == {"required_keyword_missing"}
    assert {warning["code"] for warning in result["warnings"]} == {"execution_mode_exceeds_policy"}


def test_existing_database_is_migrated_additively(tmp_path: Path) -> None:
    db_path = tmp_path / "old.sqlite"
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        CREATE TABLE experiments (
            id TEXT PRIMARY KEY, app_package TEXT NOT NULL, experiment_type TEXT NOT NULL,
            hypothesis TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'proposed',
            success_metric TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE experiment_observations (
            id INTEGER PRIMARY KEY, experiment_id TEXT NOT NULL, observed_at DATE NOT NULL,
            metric_value REAL NOT NULL, raw_data TEXT, UNIQUE(experiment_id, observed_at)
        )
        """
    )
    connection.commit()
    connection.close()

    init_db(db_path)

    connection = sqlite3.connect(db_path)
    experiment_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(experiments)").fetchall()
    }
    observation_columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(experiment_observations)").fetchall()
    }
    connection.close()
    assert {"evidence_json", "validation_json", "execution_mode", "approval_actor"} <= (
        experiment_columns
    )
    assert {"visitors", "installs", "period_start", "period_end", "source"} <= (observation_columns)


@pytest.mark.asyncio
async def test_end_to_end_execute_observe_evaluate_retain_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "experiments.sqlite"
    init_db(db_path)
    _create(db_path)
    listing = {
        "language": "en-US",
        "title": "Old App Title",
        "short_description": "Old short description",
        "full_description": "Old full description",
    }
    writes: list[dict[str, Any]] = []

    def read_listing(_package: str, _language: str) -> dict[str, Any]:
        return dict(listing)

    def write_listing(_package: str, args: dict[str, Any]) -> dict[str, Any]:
        writes.append(dict(args))
        if "title" in args:
            listing["title"] = args["title"]
        if "shortDescription" in args:
            listing["short_description"] = args["shortDescription"]
        if "fullDescription" in args:
            listing["full_description"] = args["fullDescription"]
        return {"success": True}

    lifecycle = ExperimentLifecycle(
        db_path,
        rulebook_dir=tmp_path / "rulebooks",
        listing_reader=read_listing,
        listing_writer=write_listing,
        clock=lambda: NOW,
    )
    lifecycle.approve("exp-1", actor="operator@example.com", reason="Reviewed metadata")
    executed = await lifecycle.execute("exp-1")
    repeated = await lifecycle.execute("exp-1")

    assert executed["status"] == repeated["status"] == "measuring"
    assert len(writes) == 1
    assert executed["snapshot_before"]["title"] == "Old App Title"
    assert executed["snapshot_after"]["title"] == "Better App Title"

    lifecycle.observe(
        "exp-1",
        visitors=10_000,
        installs=2_600,
        observed_at="2026-07-21",
        source="play_console_daily_country",
    )
    evaluation = lifecycle.evaluate("exp-1")
    assert evaluation["method"] == "two_proportion_z_test"
    assert evaluation["verdict"] == "winner"
    retained = lifecycle.retain("exp-1", actor="operator@example.com", reason="Winner")
    assert retained["status"] == "concluded"
    assert retained["retained_at"] is not None


@pytest.mark.asyncio
async def test_unsuccessful_writer_never_enters_measuring(tmp_path: Path) -> None:
    db_path = tmp_path / "experiments.sqlite"
    init_db(db_path)
    _create(db_path)
    lifecycle = ExperimentLifecycle(
        db_path,
        rulebook_dir=tmp_path / "rulebooks",
        listing_reader=lambda *_args: {"language": "en-US", "title": "Old"},
        listing_writer=lambda *_args: {"success": False, "error": "rejected"},
        clock=lambda: NOW,
    )
    lifecycle.approve("exp-1", actor="operator", reason="reviewed")

    with pytest.raises(LifecycleConflictError, match="unsuccessful"):
        await lifecycle.execute("exp-1")

    stored = get_db_experiment(db_path, "exp-1")
    assert stored is not None
    assert stored["status"] == "approved"
    assert json.loads(stored["snapshot_before"])["title"] == "Old"


def test_two_proportion_evaluation_uses_counts() -> None:
    result = evaluate_two_proportion_conversion(
        baseline_visitors=10_000,
        baseline_installs=2_000,
        treatment_visitors=10_000,
        treatment_installs=2_600,
        target_improvement_pct=0.10,
        rollback_degradation_pct=0.15,
    )
    assert result["verdict"] == "winner"
    assert result["baseline"] == {"visitors": 10_000, "installs": 2_000}
    assert result["treatment"] == {"visitors": 10_000, "installs": 2_600}


class TestEvaluateKeywordRankChange:
    def test_improvement_from_a_real_baseline_rank_is_a_winner(self) -> None:
        result = evaluate_keyword_rank_change(
            baseline_rank=138.0,
            latest_rank=40.0,
            target_improvement_pct=0.10,
            rollback_degradation_pct=0.15,
        )
        assert result["verdict"] == "winner"
        assert result["method"] == "rank_threshold_comparison"
        assert result["observed_change"] > 0

    def test_degradation_past_threshold_triggers_rollback(self) -> None:
        result = evaluate_keyword_rank_change(
            baseline_rank=50.0,
            latest_rank=100.0,
            target_improvement_pct=0.10,
            rollback_degradation_pct=0.15,
        )
        assert result["verdict"] == "rollback"

    def test_small_worsening_below_threshold_is_a_loser_not_a_rollback(self) -> None:
        result = evaluate_keyword_rank_change(
            baseline_rank=100.0,
            latest_rank=105.0,
            target_improvement_pct=0.10,
            rollback_degradation_pct=0.15,
        )
        assert result["verdict"] == "loser"

    def test_losing_the_ranking_entirely_is_a_rollback(self) -> None:
        result = evaluate_keyword_rank_change(
            baseline_rank=50.0,
            latest_rank=RANK_NOT_FOUND_SENTINEL,
            target_improvement_pct=0.10,
            rollback_degradation_pct=0.15,
        )
        assert result["verdict"] == "rollback"
        assert "Lost search ranking entirely" in result["reason"]

    def test_gaining_a_rank_from_unranked_is_a_winner(self) -> None:
        result = evaluate_keyword_rank_change(
            baseline_rank=RANK_NOT_FOUND_SENTINEL,
            latest_rank=180.0,
            target_improvement_pct=0.10,
            rollback_degradation_pct=0.15,
        )
        assert result["verdict"] == "winner"

    def test_staying_unranked_is_inconclusive_not_rollback(self) -> None:
        result = evaluate_keyword_rank_change(
            baseline_rank=RANK_NOT_FOUND_SENTINEL,
            latest_rank=RANK_NOT_FOUND_SENTINEL,
            target_improvement_pct=0.10,
            rollback_degradation_pct=0.15,
        )
        assert result["verdict"] == "inconclusive"


@pytest.mark.asyncio
async def test_rank_observation_and_evaluation_round_trip(tmp_path: Path) -> None:
    db_path = tmp_path / "experiments.sqlite"
    init_db(db_path)
    _create_rank(db_path, rank=138)
    listing = {
        "language": "en-US",
        "title": "Pomodori",
        "short_description": "Old subtitle",
        "full_description": "Old description",
    }

    def write_listing(_package: str, args: dict[str, Any]) -> dict[str, Any]:
        if "title" in args:
            listing["title"] = args["title"]
        return {"success": True}

    lifecycle = ExperimentLifecycle(
        db_path,
        rulebook_dir=tmp_path / "rulebooks",
        listing_reader=lambda *_args: dict(listing),
        listing_writer=write_listing,
        clock=lambda: NOW,
    )
    lifecycle.approve("exp-rank-1", actor="operator@example.com", reason="Reviewed")
    await lifecycle.execute("exp-rank-1")

    observed = lifecycle.observe(
        "exp-rank-1",
        rank=40,
        observed_at="2026-07-21",
        source="app_store_search_api",
    )
    assert observed["visitors"] is None
    assert observed["installs"] is None
    assert observed["metric_value"] == 40.0

    evaluation = lifecycle.evaluate("exp-rank-1")
    assert evaluation["method"] == "rank_threshold_comparison"
    assert evaluation["verdict"] == "winner"
    assert evaluation["baseline_rank"] == 138.0
    assert evaluation["latest_rank"] == 40.0


@pytest.mark.asyncio
async def test_rank_observation_not_found_uses_sentinel(tmp_path: Path) -> None:
    db_path = tmp_path / "experiments.sqlite"
    init_db(db_path)
    _create_rank(db_path, rank=None)
    listing = {
        "language": "en-US",
        "title": "Pomodori",
        "short_description": "s",
        "full_description": "d",
    }

    def write_listing(_package: str, args: dict[str, Any]) -> dict[str, Any]:
        if "title" in args:
            listing["title"] = args["title"]
        return {"success": True}

    lifecycle = ExperimentLifecycle(
        db_path,
        rulebook_dir=tmp_path / "rulebooks",
        listing_reader=lambda *_args: dict(listing),
        listing_writer=write_listing,
        clock=lambda: NOW,
    )
    lifecycle.approve("exp-rank-1", actor="operator@example.com", reason="Reviewed")
    await lifecycle.execute("exp-rank-1")

    observed = lifecycle.observe(
        "exp-rank-1", rank=None, observed_at="2026-07-21", source="app_store_search_api"
    )
    assert observed["metric_value"] == RANK_NOT_FOUND_SENTINEL

    evaluation = lifecycle.evaluate("exp-rank-1")
    assert evaluation["verdict"] == "inconclusive"


def test_observe_rejects_mixing_rank_and_conversion_shapes(tmp_path: Path) -> None:
    db_path = tmp_path / "experiments.sqlite"
    init_db(db_path)
    _create_rank(db_path)
    lifecycle = ExperimentLifecycle(
        db_path,
        rulebook_dir=tmp_path / "rulebooks",
        listing_reader=lambda *_args: {"language": "en-US", "title": "x"},
        listing_writer=lambda *_args: {"success": True},
        clock=lambda: NOW,
    )
    update_db_experiment_fields(db_path, "exp-rank-1", {"status": "measuring"})

    with pytest.raises(LifecycleConflictError, match="must observe rank"):
        lifecycle.observe("exp-rank-1", visitors=100, installs=10, source="app_store_search_api")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "auto_status", "approval_available"),
    [
        ("recommend_only", "proposed", False),
        ("manual", "proposed", True),
        ("auto_low_risk", "measuring", True),
    ],
)
async def test_proposal_modes_enforce_execution_authority(
    tmp_path: Path,
    mode: str,
    auto_status: str,
    approval_available: bool,
) -> None:
    db_path = tmp_path / f"{mode}.sqlite"
    init_db(db_path)
    listing = {
        "language": "en-US",
        "title": "Old App Title",
        "short_description": "Old short description",
        "full_description": "Old full description",
    }
    writes: list[dict[str, Any]] = []

    def writer(_package: str, args: dict[str, Any]) -> dict[str, bool]:
        writes.append(args)
        listing["title"] = args["title"]
        return {"success": True}

    lifecycle = ExperimentLifecycle(
        db_path,
        rulebook_dir=tmp_path / "rulebooks",
        listing_reader=lambda *_args: dict(listing),
        listing_writer=writer,
        clock=lambda: NOW,
    )
    created = lifecycle.create_proposal(_proposal(mode))
    assert created["validation"]["valid"] is True
    assert ("approve" in created["available_actions"]) is approval_available

    advanced = await lifecycle.auto_advance(created["id"])
    assert advanced["status"] == auto_status
    assert len(writes) == (1 if mode == "auto_low_risk" else 0)
    if mode == "recommend_only":
        with pytest.raises(LifecycleConflictError, match="cannot be approved"):
            lifecycle.approve(created["id"], actor="operator", reason="reviewed")


@pytest.mark.asyncio
async def test_auto_mode_downgrade_requires_review_and_never_writes(tmp_path: Path) -> None:
    db_path = tmp_path / "downgrade.sqlite"
    init_db(db_path)
    rulebooks = tmp_path / "rulebooks"
    rulebooks.mkdir()
    (rulebooks / f"{PACKAGE}.yaml").write_text(
        f"package_name: {PACKAGE}\nsafety_rules:\n  require_telegram_approval: true\n",
        encoding="utf-8",
    )
    writes: list[dict[str, Any]] = []
    lifecycle = ExperimentLifecycle(
        db_path,
        rulebook_dir=rulebooks,
        listing_reader=lambda *_args: {},
        listing_writer=lambda _package, args: writes.append(args),
        clock=lambda: NOW,
    )
    created = lifecycle.create_proposal(_proposal("auto_low_risk"))
    advanced = await lifecycle.auto_advance(created["id"])

    assert advanced["status"] == "proposed"
    assert advanced["validation"]["valid"] is True
    assert advanced["validation"]["effective_execution_mode"] == "manual"
    assert advanced["requires_review"] is True
    assert advanced["available_actions"] == ["approve", "reject"]
    assert writes == []


def test_semantic_detail_and_reject_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "detail.sqlite"
    init_db(db_path)
    lifecycle = ExperimentLifecycle(
        db_path,
        rulebook_dir=tmp_path / "rulebooks",
        clock=lambda: NOW,
    )
    created = lifecycle.create_proposal(_proposal("manual"))

    assert created["autonomy_mode"] == "manual"
    assert created["proposal"]["changes"] == [
        {"field": "title", "before": "Old App Title", "after": "Better App Title"}
    ]
    assert created["validation"]["issues"] == []
    assert created["raw_evidence"]["baseline"]["visitors"] == 10_000
    assert created["evidence"][0]["label"] == "Measured baseline"
    assert created["available_actions"] == ["approve", "reject"]
    assert "observe" not in created["available_actions"]

    monkeypatch.setattr(experiments, "_service", lambda: lifecycle)
    monkeypatch.setenv("MCP_GC_API_AUTH_REQUIRED", "1")
    monkeypatch.setenv("MCP_GC_ADMIN_API_KEY", "admin-key")
    with TestClient(app) as client:
        response = client.post(
            f"/api/experiments/{created['id']}/reject",
            json={"reason": "Copy is off-brand"},
            headers={"Authorization": "Bearer admin-key"},
        )
    assert response.status_code == 200
    rejected = response.json()["experiment"]
    assert rejected["status"] == "rejected"
    assert rejected["rejection_actor"] == "api-key:admin"
    assert rejected["rejection_reason"] == "Copy is off-brand"
    assert rejected["available_actions"] == []
    assert rejected["actions"][0]["action_type"] == "experiment_reject"


def test_actions_api_filters_by_experiment_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "actions.sqlite"
    init_db(db_path)
    _create(db_path, "exp-1")
    _create(db_path, "exp-2")
    log_db_action(db_path, "experiment_validate", experiment_id="exp-1")
    log_db_action(db_path, "experiment_validate", experiment_id="exp-2")
    monkeypatch.setattr(actions, "DEFAULT_DB_PATH", db_path)

    with TestClient(app) as client:
        response = client.get("/api/actions/?experiment_id=exp-2")

    assert response.status_code == 200
    assert [item["experiment_id"] for item in response.json()["actions"]] == ["exp-2"]


def test_experiment_catalog_and_planning_only_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "planned.sqlite"
    init_db(db_path)
    lifecycle = ExperimentLifecycle(db_path, rulebook_dir=tmp_path / "rulebooks", clock=lambda: NOW)
    monkeypatch.setattr(experiments, "DEFAULT_DB_PATH", db_path)
    monkeypatch.setattr(experiments, "_service", lambda: lifecycle)
    monkeypatch.setattr(
        experiments,
        "_load_apps_config",
        lambda: [{"package_name": PACKAGE, "display_name": "Example App"}],
    )

    with TestClient(app) as client:
        catalog = client.get("/api/experiments/types")
        created = client.post(
            "/api/experiments/planned",
            json={
                "app_package": PACKAGE,
                "experiment_type": "paywall_variant",
                "hypothesis": "A shorter paywall will improve trial conversion",
                "success_metric": "trial_to_paid_conversion_rate",
                "min_observation_days": 7,
                "max_observation_days": 21,
                "notes": "Waiting for a rollback-capable RevenueCat executor.",
            },
        )
        aso = client.post(
            "/api/experiments/planned",
            json={
                "app_package": PACKAGE,
                "experiment_type": "aso_metadata",
                "hypothesis": "A clearer title improves store conversion",
            },
        )

    assert catalog.status_code == 200
    type_ids = {item["id"] for item in catalog.json()["experiment_types"]}
    assert {
        "aso_metadata",
        "store_creative",
        "paywall_variant",
        "pricing_experiment",
        "ad_unit_config",
        "push_campaign",
        "ua_budget",
        "remote_config",
    } <= type_ids
    assert created.status_code == 200
    experiment = created.json()["experiment"]
    assert experiment["status"] == "proposed"
    assert experiment["experiment_type"] == "paywall_variant"
    assert experiment["execution_mode"] == "recommend_only"
    assert experiment["target_tool"] is None
    assert experiment["available_actions"] == ["reject"]
    assert experiment["raw_evidence"]["planning"]["execution_supported"] is False
    assert aso.status_code == 409


def test_semantic_api_golden_path_and_protected_patch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "api.sqlite"
    init_db(db_path)
    listing = {
        "language": "en-US",
        "title": "Old App Title",
        "short_description": "Old short description",
        "full_description": "Old full description",
    }

    def read_listing(_package: str, _language: str) -> dict[str, Any]:
        return dict(listing)

    def write_listing(_package: str, args: dict[str, Any]) -> dict[str, bool]:
        if "title" in args:
            listing["title"] = args["title"]
        return {"success": True}

    lifecycle = ExperimentLifecycle(
        db_path,
        rulebook_dir=tmp_path / "rulebooks",
        listing_reader=read_listing,
        listing_writer=write_listing,
        clock=lambda: NOW,
    )
    monkeypatch.setattr(experiments, "DEFAULT_DB_PATH", db_path)
    monkeypatch.setattr(experiments, "_service", lambda: lifecycle)
    monkeypatch.setenv("MCP_GC_DEV_ALLOW_GENERIC_EXECUTABLE_PROPOSALS", "1")

    with TestClient(app) as client:
        created = client.post(
            "/api/experiments/",
            json={
                "app_package": PACKAGE,
                "experiment_type": "aso_metadata",
                "hypothesis": "A clearer title improves conversion",
                "success_metric": "store_view_to_install_rate",
                "target_tool": "play_store/update_listing",
                "target_args": {
                    "packageName": PACKAGE,
                    "language": "en-US",
                    "title": "Better App Title",
                },
                "min_observation_days": 1,
                "execution_mode": "manual",
                "evidence": _evidence(),
            },
        )
        experiment_id = created.json()["id"]
        protected = client.patch(f"/api/experiments/{experiment_id}", json={"status": "measuring"})
        assert protected.status_code == 422
        assert client.post(f"/api/experiments/{experiment_id}/validate").json()["validation"][
            "valid"
        ]
        assert (
            client.post(
                f"/api/experiments/{experiment_id}/approve",
                json={"reason": "reviewed"},
            ).status_code
            == 200
        )
        assert client.post(f"/api/experiments/{experiment_id}/execute").status_code == 200
        assert (
            client.post(
                f"/api/experiments/{experiment_id}/observe",
                json={
                    "visitors": 10_000,
                    "installs": 2_600,
                    "observed_at": "2026-07-21",
                    "source": "play_console_daily_country",
                },
            ).status_code
            == 200
        )
        evaluated = client.post(f"/api/experiments/{experiment_id}/evaluate")
        assert evaluated.json()["evaluation"]["verdict"] == "winner"
        retained = client.post(
            f"/api/experiments/{experiment_id}/retain",
            json={"reason": "winner"},
        )
        assert retained.json()["experiment"]["status"] == "concluded"
        detail = client.get(f"/api/experiments/{experiment_id}").json()
        assert detail["snapshot_after"]["title"] == "Better App Title"
        assert detail["observations"][0]["visitors"] == 10_000
        rolled_back = client.post(
            f"/api/experiments/{experiment_id}/rollback",
            json={"reason": "post-test restore"},
        )
        assert rolled_back.json()["experiment"]["status"] == "rolled_back"
        assert rolled_back.json()["experiment"]["actual_listing"]["title"] == "Better App Title"
        assert listing["title"] == "Old App Title"


@pytest.mark.asyncio
async def test_read_only_guard_blocks_lifecycle_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "read-only.sqlite"
    init_db(db_path)
    _create(db_path)
    writes: list[dict[str, Any]] = []
    lifecycle = ExperimentLifecycle(
        db_path,
        rulebook_dir=tmp_path / "rulebooks",
        listing_reader=lambda *_args: {"language": "en-US", "title": "Old App Title"},
        listing_writer=lambda _package, args: writes.append(args),
        clock=lambda: NOW,
    )
    lifecycle.approve("exp-1", actor="operator", reason="reviewed")
    monkeypatch.setenv("MCP_GC_READ_ONLY", "1")

    with pytest.raises(LifecycleConflictError, match="MCP_GC_READ_ONLY"):
        await lifecycle.execute("exp-1")

    assert writes == []
    assert get_db_experiment(db_path, "exp-1")["status"] == "approved"  # type: ignore[index]


@pytest.mark.asyncio
async def test_system_approval_loses_authority_after_manual_policy_downgrade(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "policy-downgrade.sqlite"
    init_db(db_path)
    rulebooks = tmp_path / "rulebooks"
    rulebooks.mkdir()
    listing = {
        "language": "en-US",
        "title": "Old App Title",
        "short_description": "Old short description",
        "full_description": "Old full description",
    }
    writes: list[dict[str, Any]] = []
    lifecycle = ExperimentLifecycle(
        db_path,
        rulebook_dir=rulebooks,
        listing_reader=lambda *_args: dict(listing),
        listing_writer=lambda _package, args: writes.append(args),
        clock=lambda: NOW,
    )
    created = lifecycle.create_proposal(_proposal("auto_low_risk"))
    lifecycle.approve(
        created["id"], actor="system:auto_low_risk", reason="validated automatic proposal"
    )
    (rulebooks / f"{PACKAGE}.yaml").write_text(
        f"package_name: {PACKAGE}\nsafety_rules:\n  require_manual_approval: true\n",
        encoding="utf-8",
    )

    with pytest.raises(LifecycleConflictError, match="automatic execution authority"):
        await lifecycle.execute(created["id"])

    stored = get_db_experiment(db_path, created["id"])
    assert stored is not None
    assert json.loads(stored["approval_validation_json"])["effective_execution_mode"] == (
        "auto_low_risk"
    )
    assert writes == []


@pytest.mark.asyncio
async def test_rollback_claim_rejects_remote_drift_and_stays_reconciliation_state(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "rollback-drift.sqlite"
    init_db(db_path)
    _create(db_path)
    listing = {
        "language": "en-US",
        "title": "Old App Title",
        "short_description": None,
        "full_description": None,
    }
    writes: list[dict[str, Any]] = []

    def writer(_package: str, args: dict[str, Any]) -> dict[str, bool]:
        writes.append(args)
        listing["title"] = args["title"]
        return {"success": True}

    lifecycle = ExperimentLifecycle(
        db_path,
        rulebook_dir=tmp_path / "rulebooks",
        listing_reader=lambda *_args: dict(listing),
        listing_writer=writer,
        clock=lambda: NOW,
    )
    lifecycle.approve("exp-1", actor="operator", reason="reviewed")
    await lifecycle.execute("exp-1")
    listing["title"] = "Newer operator edit"

    with pytest.raises(LifecycleConflictError, match="snapshot_after"):
        await lifecycle.rollback("exp-1", actor="operator", reason="restore")

    assert len(writes) == 1
    assert get_db_experiment(db_path, "exp-1")["status"] == "rolling_back"  # type: ignore[index]


@pytest.mark.asyncio
async def test_rollback_brake_rejects_before_claim(tmp_path: Path) -> None:
    db_path = tmp_path / "rollback-brake.sqlite"
    init_db(db_path)
    _create(db_path)
    listing = {"language": "en-US", "title": "Old App Title"}

    def writer(_package: str, args: dict[str, Any]) -> dict[str, bool]:
        listing["title"] = args["title"]
        return {"success": True}

    lifecycle = ExperimentLifecycle(
        db_path,
        rulebook_dir=tmp_path / "rulebooks",
        listing_reader=lambda *_args: dict(listing),
        listing_writer=writer,
        clock=lambda: NOW,
    )
    lifecycle.approve("exp-1", actor="operator", reason="reviewed")
    await lifecycle.execute("exp-1")
    set_emergency_brake(db_path, PACKAGE, "critical vitals")

    with pytest.raises(LifecycleConflictError, match="Emergency brake"):
        await lifecycle.rollback("exp-1", actor="operator", reason="restore")

    assert get_db_experiment(db_path, "exp-1")["status"] == "measuring"  # type: ignore[index]


@pytest.mark.asyncio
async def test_unknown_rollback_dispatch_remains_non_retryable(tmp_path: Path) -> None:
    db_path = tmp_path / "rollback-unknown.sqlite"
    init_db(db_path)
    _create(db_path)
    listing = {"language": "en-US", "title": "Old App Title"}
    calls = 0

    def writer(_package: str, args: dict[str, Any]) -> dict[str, bool]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise TimeoutError("outcome unknown")
        listing["title"] = args["title"]
        return {"success": True}

    lifecycle = ExperimentLifecycle(
        db_path,
        rulebook_dir=tmp_path / "rulebooks",
        listing_reader=lambda *_args: dict(listing),
        listing_writer=writer,
        clock=lambda: NOW,
    )
    lifecycle.approve("exp-1", actor="operator", reason="reviewed")
    await lifecycle.execute("exp-1")

    with pytest.raises(TimeoutError, match="outcome unknown"):
        await lifecycle.rollback("exp-1", actor="operator", reason="restore")

    assert get_db_experiment(db_path, "exp-1")["status"] == "rolling_back"  # type: ignore[index]
    with pytest.raises(LifecycleConflictError, match="rolling_back"):
        await lifecycle.rollback("exp-1", actor="operator", reason="retry")


@pytest.mark.asyncio
async def test_observation_windows_and_automatic_rollback_minimums(tmp_path: Path) -> None:
    db_path = tmp_path / "observation-safety.sqlite"
    init_db(db_path)
    _create(db_path)
    listing = {"language": "en-US", "title": "Old App Title"}

    def writer(_package: str, args: dict[str, Any]) -> dict[str, bool]:
        listing["title"] = args["title"]
        return {"success": True}

    lifecycle = ExperimentLifecycle(
        db_path,
        rulebook_dir=tmp_path / "rulebooks",
        listing_reader=lambda *_args: dict(listing),
        listing_writer=writer,
        clock=lambda: NOW,
    )
    lifecycle.approve("exp-1", actor="operator", reason="reviewed")
    await lifecycle.execute("exp-1")

    with pytest.raises(LifecycleConflictError, match="strictly after"):
        lifecycle.observe(
            "exp-1",
            visitors=500,
            installs=10,
            observed_at="2026-07-20",
            source="play_console_daily_country",
        )
    lifecycle.observe(
        "exp-1",
        visitors=500,
        installs=10,
        observed_at="2026-07-21",
        source="play_console_daily_country",
    )
    with pytest.raises(LifecycleConflictError, match="overlaps"):
        lifecycle.observe(
            "exp-1",
            visitors=500,
            installs=10,
            observed_at="2026-07-22",
            period_start="2026-07-21",
            period_end="2026-07-22",
            source="play_console_daily_country",
        )

    evaluation = lifecycle.evaluate("exp-1")
    assert evaluation["verdict"] == "insufficient_data"
    assert evaluation["treatment"]["visitors"] == 500


def test_positive_below_target_and_low_confidence_harm_do_not_rollback() -> None:
    positive = evaluate_two_proportion_conversion(
        baseline_visitors=100_000,
        baseline_installs=20_000,
        treatment_visitors=100_000,
        treatment_installs=21_000,
        target_improvement_pct=0.10,
        rollback_degradation_pct=0.15,
    )
    noisy_harm = evaluate_two_proportion_conversion(
        baseline_visitors=10,
        baseline_installs=5,
        treatment_visitors=10,
        treatment_installs=2,
        target_improvement_pct=0.10,
        rollback_degradation_pct=0.15,
    )

    assert positive["verdict"] == "inconclusive"
    assert noisy_harm["verdict"] == "insufficient_data"
    assert noisy_harm["confidence"] < 0.9
