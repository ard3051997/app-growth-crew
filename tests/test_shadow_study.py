"""Integration test for the shadow-mode experimental study runner."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest

import run_shadow_study
from app_manager.shadow_lifecycle import ShadowListingStore
from app_manager.store_conversion_proposals import ListingProvenance, ListingSnapshot
from funnel_engine.db import get_db_experiments, init_db

if TYPE_CHECKING:
    from pathlib import Path

PACKAGE = "com.shadow.example"


class _FakeOptimizedListing:
    suggested_title = "Better App Title"
    suggested_short_description = "A clearer, benefit-led short description"
    suggested_description = (
        "A clearer full description that explains the app's core value proposition "
        "in enough detail to pass listing text validation checks."
    )


class _FakeASOClient:
    def generate_optimized_listing(self, **_kwargs: Any) -> _FakeOptimizedListing:
        return _FakeOptimizedListing()


def _funnel() -> dict[str, Any]:
    return {
        "data_sources": ["play_store_mcp", "analytics_mcp"],
        "leaks": [
            {
                "name": "Store View → Install",
                "conversion_rate": 0.18,
                "benchmark_rate": 0.25,
                "gap": -0.07,
                "users_entered": 10_000,
                "users_completed": 1_800,
                "monthly_revenue_impact": 4_000,
                "priority": "critical",
                "insight": "Store conversion is below benchmark.",
                "has_data": True,
            }
        ],
    }


def _country_rows() -> list[dict[str, Any]]:
    today = datetime.now(UTC).date()
    return [
        {
            "date": (today - timedelta(days=offset)).isoformat(),
            "country": "us",
            "visitors": 1_000,
            "installs": 200,
        }
        for offset in range(7)
    ]


@pytest.mark.asyncio
async def test_shadow_cycle_reaches_measuring_without_touching_the_production_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ShadowListingStore, "_seed", staticmethod(lambda *_args: {}))

    shadow_db = tmp_path / "shadow.db"
    production_db = tmp_path / "production.db"
    init_db(production_db)

    rulebook_dir = tmp_path / "rulebooks"
    rulebook_dir.mkdir()
    (rulebook_dir / f"{PACKAGE}.yaml").write_text(
        f"package_name: {PACKAGE}\naso_strategy:\n  target_keywords: []\n"
    )

    monkeypatch.setattr(run_shadow_study, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(run_shadow_study, "DEFAULT_DB_PATH", production_db)
    monkeypatch.setattr(
        run_shadow_study,
        "_load_apps_config",
        lambda: [{"package_name": PACKAGE, "app_category": "utilities"}],
    )
    monkeypatch.setattr(
        run_shadow_study,
        "get_latest_app_snapshot",
        lambda _db, _pkg: {
            "raw_funnel_json": json.dumps(_funnel()),
            "data_as_of": datetime.now(UTC).isoformat(),
        },
    )
    monkeypatch.setattr(
        run_shadow_study, "get_country_performance", lambda _db, _pkg: _country_rows()
    )
    monkeypatch.setattr(
        run_shadow_study,
        "_get_live_listing",
        lambda _package, language: ListingSnapshot(
            title="Old Title",
            short_description="Old short description",
            full_description="Old full description that is reasonably long for validation.",
            language=language,
            provenance=ListingProvenance(
                source="google_play_developer_api", live=True, retrieved_at=datetime.now(UTC)
            ),
        ),
    )
    monkeypatch.setattr(run_shadow_study, "ASOClient", _FakeASOClient)

    result = await run_shadow_study.run_shadow_cycle(db_path=shadow_db)

    assert len(result["apps"]) == 1
    app_result = result["apps"][0]
    assert app_result["app_package"] == PACKAGE
    assert app_result["status"] in {"measuring", "concluded"}, app_result
    assert app_result["would_have_executed"] is True

    shadow_experiments = get_db_experiments(shadow_db)
    assert len(shadow_experiments) == 1
    assert shadow_experiments[0]["status"] == app_result["status"]
    assert shadow_experiments[0]["execution_mode"] == "auto_low_risk"

    assert get_db_experiments(production_db) == []


@pytest.mark.asyncio
async def test_apps_without_a_rulebook_are_skipped_not_errored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run_shadow_study, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        run_shadow_study,
        "_load_apps_config",
        lambda: [{"package_name": "com.no.rulebook", "app_category": "utilities"}],
    )

    result = await run_shadow_study.run_shadow_cycle(db_path=tmp_path / "shadow.db")

    assert result["apps"] == [
        {"app_package": "com.no.rulebook", "status": "skipped", "reason": "no_rulebook"}
    ]
