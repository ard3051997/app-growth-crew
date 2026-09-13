"""Tests for cross-portfolio experiment opportunity ranking."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from app_manager import portfolio_opportunities as portfolio_opportunities_module
from app_manager.portfolio_opportunities import rank_portfolio_opportunities


def _funnel(*, monthly_revenue_impact: float, stage: str = "Store View → Install") -> dict:
    return {
        "data_sources": ["play_store_mcp", "analytics_mcp"],
        "leaks": [
            {
                "name": stage,
                "conversion_rate": 0.18,
                "benchmark_rate": 0.25,
                "gap": -0.07,
                "users_entered": 10_000,
                "users_completed": 1_800,
                "monthly_revenue_impact": monthly_revenue_impact,
                "priority": "critical",
                "insight": f"{stage} is below benchmark.",
                "has_data": True,
            }
        ],
    }


def test_ranks_opportunities_across_apps_by_estimated_impact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_at = datetime.now(UTC).isoformat()

    monkeypatch.setattr(
        portfolio_opportunities_module,
        "_load_apps_config",
        lambda: [
            {"package_name": "com.small.app"},
            {"package_name": "com.big.app"},
        ],
    )
    monkeypatch.setattr(
        portfolio_opportunities_module,
        "get_all_latest_snapshots",
        lambda _db_path: [
            {
                "package_name": "com.small.app",
                "raw_funnel_json": json.dumps(_funnel(monthly_revenue_impact=500)),
                "data_as_of": captured_at,
            },
            {
                "package_name": "com.big.app",
                "raw_funnel_json": json.dumps(_funnel(monthly_revenue_impact=50_000)),
                "data_as_of": captured_at,
            },
        ],
    )
    monkeypatch.setattr(
        portfolio_opportunities_module, "get_db_experiments", lambda *_args, **_kwargs: []
    )

    result = rank_portfolio_opportunities(top_n=5)

    assert result["apps_scanned"] == 2
    assert result["apps_with_data"] == 2
    assert result["apps_without_data"] == []
    assert result["total_opportunities_found"] == len(result["top_opportunities"])
    assert result["top_opportunities"][0]["app_package"] == "com.big.app"
    assert result["top_opportunities"][0]["portfolio_rank"] == 1
    assert result["top_opportunities"][-1]["app_package"] == "com.small.app"


def test_skips_apps_without_a_cached_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        portfolio_opportunities_module,
        "_load_apps_config",
        lambda: [
            {"package_name": "com.no.snapshot"},
            {"package_name": "com.has.snapshot"},
        ],
    )
    monkeypatch.setattr(
        portfolio_opportunities_module,
        "get_all_latest_snapshots",
        lambda _db_path: [
            {
                "package_name": "com.has.snapshot",
                "raw_funnel_json": json.dumps(_funnel(monthly_revenue_impact=1_000)),
                "data_as_of": datetime.now(UTC).isoformat(),
            },
        ],
    )
    monkeypatch.setattr(
        portfolio_opportunities_module, "get_db_experiments", lambda *_args, **_kwargs: []
    )

    result = rank_portfolio_opportunities()

    assert result["apps_scanned"] == 2
    assert result["apps_with_data"] == 1
    assert result["apps_without_data"] == ["com.no.snapshot"]
    assert all(item["app_package"] == "com.has.snapshot" for item in result["top_opportunities"])


def test_matches_direct_recommender_call_for_a_single_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app_manager.experiment_recommender import recommend_experiment_designs

    captured_at = datetime.now(UTC).isoformat()
    funnel = _funnel(monthly_revenue_impact=2_500)

    monkeypatch.setattr(
        portfolio_opportunities_module,
        "_load_apps_config",
        lambda: [{"package_name": "com.solo.app"}],
    )
    monkeypatch.setattr(
        portfolio_opportunities_module,
        "get_all_latest_snapshots",
        lambda _db_path: [
            {
                "package_name": "com.solo.app",
                "raw_funnel_json": json.dumps(funnel),
                "data_as_of": captured_at,
            },
        ],
    )
    monkeypatch.setattr(
        portfolio_opportunities_module, "get_db_experiments", lambda *_args, **_kwargs: []
    )

    portfolio_result = rank_portfolio_opportunities(top_n=5)
    direct_result = recommend_experiment_designs(
        package_name="com.solo.app",
        funnel=funnel,
        captured_at=captured_at,
        max_results=3,
    )

    portfolio_types = [item["experiment_type"] for item in portfolio_result["top_opportunities"]]
    direct_types = [item["experiment_type"] for item in direct_result["recommendations"]]
    assert portfolio_types == direct_types
