"""Portfolio-wide opportunity ranking.

Aggregates recommend_experiment_designs() across every app in config/apps.json that has
a cached funnel snapshot, so a human can see the single highest-impact experiment to run
next across the whole portfolio instead of picking one app at a time. No new statistics —
this is aggregation over the existing per-app scoring in experiment_recommender.py.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app_manager.credential_store import _load_apps_config
from app_manager.experiment_recommender import recommend_experiment_designs
from funnel_engine.db import DEFAULT_DB_PATH, get_all_latest_snapshots, get_db_experiments

if TYPE_CHECKING:
    from pathlib import Path

ACTIVE_EXPERIMENT_STATUSES = {"approved", "active", "measuring", "rolling_back"}


def rank_portfolio_opportunities(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    focus: str = "auto",
    max_results_per_app: int = 3,
    top_n: int = 10,
) -> dict[str, Any]:
    """Rank experiment opportunities across every app with a cached funnel snapshot.

    Sorts the merged list the same way each app's own recommendations are sorted:
    non-conflicting first, then highest estimated monthly impact, then executable
    before planning-only.
    """
    apps = _load_apps_config()
    snapshots_by_package = {
        str(row["package_name"]): row for row in get_all_latest_snapshots(db_path)
    }

    all_recommendations: list[dict[str, Any]] = []
    scanned: list[str] = []
    skipped_no_snapshot: list[str] = []

    for app in apps:
        package_name = app.get("package_name")
        if not package_name:
            continue
        scanned.append(package_name)

        snapshot = snapshots_by_package.get(package_name)
        funnel = None
        if snapshot and snapshot.get("raw_funnel_json"):
            try:
                parsed = json.loads(snapshot["raw_funnel_json"])
            except (TypeError, json.JSONDecodeError):
                parsed = None
            if isinstance(parsed, dict):
                funnel = parsed
        if funnel is None:
            skipped_no_snapshot.append(package_name)
            continue

        captured_at = snapshot.get("data_as_of") or snapshot.get("created_at")
        active_types = {
            str(experiment["experiment_type"])
            for experiment in get_db_experiments(db_path, app_package=package_name)
            if experiment.get("status") in ACTIVE_EXPERIMENT_STATUSES
        }
        result = recommend_experiment_designs(
            package_name=package_name,
            funnel=funnel,
            captured_at=captured_at,
            focus=focus,
            max_results=max_results_per_app,
            active_experiment_types=active_types,
        )
        all_recommendations.extend(result["recommendations"])

    all_recommendations.sort(
        key=lambda item: (
            item["conflicts_with_active_experiment"],
            -item["estimated_monthly_impact"],
            0 if item["capability"] == "executable" else 1,
        )
    )
    top = all_recommendations[:top_n]
    for portfolio_rank, recommendation in enumerate(top, 1):
        recommendation["portfolio_rank"] = portfolio_rank

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "focus": focus,
        "apps_scanned": len(scanned),
        "apps_with_data": len(scanned) - len(skipped_no_snapshot),
        "apps_without_data": skipped_no_snapshot,
        "total_opportunities_found": len(all_recommendations),
        "top_opportunities": top,
    }


if __name__ == "__main__":
    print(json.dumps(rank_portfolio_opportunities(), indent=2, default=str))
