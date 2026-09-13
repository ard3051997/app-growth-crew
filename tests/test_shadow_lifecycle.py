"""Tests for the shadow-mode fake listing store and lifecycle wiring."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest

from app_manager import shadow_lifecycle as shadow_lifecycle_module
from app_manager.credential_store import AppCredentials
from app_manager.experiment_lifecycle import ExperimentLifecycle
from app_manager.shadow_lifecycle import ShadowListingStore, build_shadow_lifecycle
from app_store_mcp.client import AppStoreClient
from funnel_engine.db import create_db_experiment, get_db_experiments, init_db
from play_store_mcp.client import PlayStoreClient

if TYPE_CHECKING:
    from pathlib import Path

PACKAGE = "com.example.app"


def _seeded_listing(_package: str, language: str) -> dict[str, Any]:
    return {
        "language": language,
        "title": "Old App Title",
        "short_description": "Old short description",
        "full_description": "Old full description",
        "video": None,
    }


def test_read_seeds_once_and_write_updates_only_provided_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ShadowListingStore, "_seed", staticmethod(_seeded_listing))
    store = ShadowListingStore()

    first = store.read(PACKAGE, "en-US")
    second = store.read(PACKAGE, "en-US")
    assert first == second
    assert first["title"] == "Old App Title"

    written = store.write(PACKAGE, {"language": "en-US", "title": "New App Title"})
    assert written["title"] == "New App Title"
    assert written["short_description"] == "Old short description"

    after_write = store.read(PACKAGE, "en-US")
    assert after_write["title"] == "New App Title"


def test_write_before_any_read_still_records_state() -> None:
    store = ShadowListingStore()
    written = store.write(
        PACKAGE, {"language": "en-US", "title": "Brand New Title", "shortDescription": "New short"}
    )
    assert written["title"] == "Brand New Title"
    assert written["short_description"] == "New short"


def test_build_shadow_lifecycle_returns_a_real_lifecycle_against_a_shadow_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ShadowListingStore, "_seed", staticmethod(_seeded_listing))
    shadow_db = tmp_path / "shadow.db"

    lifecycle = build_shadow_lifecycle(shadow_db)

    assert isinstance(lifecycle, ExperimentLifecycle)
    assert lifecycle.db_path == shadow_db
    assert get_db_experiments(shadow_db) == []


@pytest.mark.asyncio
async def test_shadow_execute_never_calls_a_real_play_store_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        shadow_lifecycle_module.ShadowListingStore, "_seed", staticmethod(_seeded_listing)
    )

    def _fail_if_called(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("A real Play Store write must never be called in shadow mode")

    monkeypatch.setattr(PlayStoreClient, "update_listing", _fail_if_called, raising=False)

    production_db = tmp_path / "production.db"
    shadow_db = tmp_path / "shadow.db"
    init_db(production_db)

    lifecycle = build_shadow_lifecycle(shadow_db)
    create_db_experiment(
        shadow_db,
        "exp-1",
        PACKAGE,
        "aso_metadata",
        "A clearer title improves listing conversion",
        "store_view_to_install_rate",
        min_observation_days=1,
        max_observation_days=7,
        target_tool="play_store/update_listing",
        target_args=json.dumps(
            {"packageName": PACKAGE, "language": "en-US", "title": "Better App Title"}
        ),
        target_improvement_pct=0.10,
        rollback_degradation_pct=0.15,
        evidence_json=json.dumps(
            {
                "baseline": {
                    "metric": "store_view_to_install_rate",
                    "locale": "en-US",
                    "visitors": 10_000,
                    "installs": 2_000,
                    "measured_at": datetime.now(UTC).isoformat(),
                    "period_end": datetime.now(UTC).date().isoformat(),
                    "source": "play_console_gcs_store_performance",
                }
            }
        ),
        execution_mode="auto_low_risk",
    )
    lifecycle.validate("exp-1")

    advanced = await lifecycle.auto_advance("exp-1")

    assert advanced["status"] in {"measuring", "concluded"}
    assert advanced["snapshot_after"]["title"] == "Better App Title"

    assert get_db_experiments(shadow_db)[0]["status"] == advanced["status"]
    assert get_db_experiments(production_db) == []


@pytest.mark.asyncio
async def test_shadow_execute_works_for_an_app_store_connect_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same auto_low_risk pipeline must work for an iOS app, not just Play Store."""
    ios_package = "com.pomodoro.example"

    monkeypatch.setattr(
        shadow_lifecycle_module.store_listing_client,
        "get_app_credentials",
        lambda _pkg: AppCredentials(
            package_name=ios_package, rc_platform="app_store", asc_profile="LightRayKey"
        ),
    )

    def _fail_if_called(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("A real App Store Connect write must never be called in shadow mode")

    monkeypatch.setattr(AppStoreClient, "update_listing", _fail_if_called, raising=False)

    mock_app_store_client = MagicMock(spec=AppStoreClient)
    mock_app_store_client.get_asc_listing.return_value = {
        "packageName": ios_package,
        "language": "en-GB",
        "title": "Old Title",
        "short_description": "Old subtitle",
        "full_description": "Old description",
    }
    monkeypatch.setattr(
        shadow_lifecycle_module.store_listing_client,
        "AppStoreClient",
        lambda: mock_app_store_client,
    )

    rulebook_dir = tmp_path / "rulebooks"
    rulebook_dir.mkdir()
    (rulebook_dir / f"{ios_package}.yaml").write_text(
        f'package_name: "{ios_package}"\nexecutable_locale: "en-GB"\n'
    )

    shadow_db = tmp_path / "shadow.db"
    lifecycle = build_shadow_lifecycle(shadow_db, rulebook_dir=rulebook_dir)
    create_db_experiment(
        shadow_db,
        "exp-ios-1",
        ios_package,
        "aso_metadata",
        "A clearer title improves listing conversion",
        "store_view_to_install_rate",
        min_observation_days=1,
        max_observation_days=7,
        target_tool="app_store_connect/update_listing",
        target_args=json.dumps(
            {"packageName": ios_package, "language": "en-GB", "title": "Better App Title"}
        ),
        target_improvement_pct=0.10,
        rollback_degradation_pct=0.15,
        evidence_json=json.dumps(
            {
                "baseline": {
                    "metric": "store_view_to_install_rate",
                    "locale": "en-GB",
                    "visitors": 10_000,
                    "installs": 2_000,
                    "measured_at": datetime.now(UTC).isoformat(),
                    "source": "play_console_gcs_store_performance",
                }
            }
        ),
        execution_mode="auto_low_risk",
    )
    lifecycle.validate("exp-ios-1")

    advanced = await lifecycle.auto_advance("exp-ios-1")

    assert advanced["status"] in {"measuring", "concluded"}
    assert advanced["snapshot_after"]["title"] == "Better App Title"
    mock_app_store_client.get_asc_listing.assert_called()
