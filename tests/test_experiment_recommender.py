"""Tests for MCP-evidence experiment design recommendations."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from api_server.main import app
from api_server.routes import apps
from app_manager.experiment_recommender import recommend_experiment_designs

PACKAGE = "com.example.app"


def _funnel() -> dict:
    return {
        "data_sources": ["play_store_mcp", "analytics_mcp", "revenuecat_mcp"],
        "leaks": [
            {
                "name": "Store View → Install",
                "conversion_rate": 0.18,
                "benchmark_rate": 0.25,
                "gap": -0.07,
                "users_entered": 10_000,
                "users_completed": 1_800,
                "monthly_revenue_impact": 4_200,
                "priority": "critical",
                "insight": "Store conversion is below benchmark.",
                "has_data": True,
            },
            {
                "name": "Install → Day 7 Retained",
                "conversion_rate": 0.12,
                "benchmark_rate": 0.20,
                "gap": -0.08,
                "users_entered": 1_800,
                "users_completed": 216,
                "monthly_revenue_impact": 1_100,
                "priority": "high",
                "insight": "Retention is below benchmark.",
                "has_data": True,
            },
            {
                "name": "Trial Start → Paid Conversion",
                "conversion_rate": 0.1,
                "benchmark_rate": 0.4,
                "gap": -0.3,
                "monthly_revenue_impact": 9_999,
                "has_data": False,
            },
        ],
    }


def test_recommender_ranks_observed_designs_and_includes_complete_evidence() -> None:
    result = recommend_experiment_designs(
        package_name=PACKAGE,
        funnel=_funnel(),
        captured_at=datetime.now(UTC).isoformat(),
        max_results=3,
    )

    assert result["source_status"] == "fresh"
    assert result["data_sources"] == [
        "play_store_mcp",
        "analytics_mcp",
        "revenuecat_mcp",
    ]
    assert [item["experiment_type"] for item in result["recommendations"]] == [
        "aso_metadata",
        "store_creative",
        "push_campaign",
    ]
    top = result["recommendations"][0]
    assert top["rank"] == 1
    assert top["capability"] == "executable"
    assert top["success_metric"] == "store_view_to_install_rate"
    assert top["evidence"]["actual_rate"] == pytest.approx(0.18)
    assert top["evidence"]["benchmark_rate"] == pytest.approx(0.25)
    assert top["evidence"]["sources"] == result["data_sources"]
    assert top["design"]["control"]
    assert top["design"]["treatment"]
    assert top["design"]["guardrail_metrics"]
    assert all("Trial Start" not in item["evidence"]["stage"] for item in result["recommendations"])


def test_recommender_filters_focus_and_marks_active_conflicts() -> None:
    result = recommend_experiment_designs(
        package_name=PACKAGE,
        funnel=_funnel(),
        captured_at=datetime.now(UTC).isoformat(),
        focus="retention",
        max_results=5,
        active_experiment_types={"push_campaign"},
    )

    assert {item["focus"] for item in result["recommendations"]} == {"retention"}
    push = next(
        item for item in result["recommendations"] if item["experiment_type"] == "push_campaign"
    )
    assert push["conflicts_with_active_experiment"] is True
    assert result["recommendations"][-1]["experiment_type"] == "push_campaign"


def test_recommendation_endpoint_uses_cached_mcp_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_at = datetime.now(UTC).isoformat()
    monkeypatch.setattr(
        apps,
        "get_app_metadata",
        lambda package: {"package_name": package, "app_category": "utilities"},
    )
    monkeypatch.setattr(
        apps,
        "get_latest_app_snapshot",
        lambda *_args: {
            "raw_funnel_json": json.dumps(_funnel()),
            "data_as_of": captured_at,
        },
    )
    monkeypatch.setattr(apps, "get_db_experiments", lambda *_args, **_kwargs: [])

    with TestClient(app) as client:
        response = client.post(
            f"/api/apps/{PACKAGE}/experiment-recommendations",
            json={"focus": "acquisition", "max_results": 2},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["snapshot_source"] == "cached_mcp_snapshot"
    assert len(body["recommendations"]) == 2
    assert body["recommendations"][0]["experiment_type"] == "aso_metadata"
