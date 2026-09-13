"""Shadow-mode experimental study for the autonomous experiment loop.

Runs the real `auto_low_risk` proposal -> approve -> execute pipeline
(app_manager.experiment_lifecycle.ExperimentLifecycle) against real portfolio
funnel evidence and real ASO-generated listing copy, but against a throwaway
SQLite database with a fake listing writer (app_manager.shadow_lifecycle) so no
call in this module ever mutates a real Play Store listing.

This answers "what would the autonomous loop actually do" with real data, at
zero product/financial risk, before any real auto-execution pilot is considered.
See docs/remaining.md's "P2: Auto-Low-Risk Pilot" checklist for what would still be
required before running any of this for real.

Usage:
    uv run python -m run_shadow_study
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

import structlog

from app_manager import store_listing_client
from app_manager.credential_store import PROJECT_ROOT, _load_apps_config, get_app_credentials
from app_manager.experiment_lifecycle import ExperimentLifecycle, LifecycleError
from app_manager.experiment_recommender import recommend_experiment_designs
from app_manager.experiment_validation import EXECUTABLE_LOCALE
from app_manager.shadow_lifecycle import build_shadow_lifecycle
from app_manager.store_conversion_proposals import (
    ListingText,
    ProposalDataError,
    StoreConversionProposalRequest,
    build_store_conversion_proposal,
    load_rulebook,
    make_listing_snapshot,
)
from aso_keyword_mcp.client import ASOClient
from funnel_engine.db import (
    DEFAULT_DB_PATH,
    get_country_performance,
    get_db_experiments,
    get_latest_app_snapshot,
)

if TYPE_CHECKING:
    from pathlib import Path

logger = structlog.get_logger(__name__)

SHADOW_DB_PATH = PROJECT_ROOT / "data" / "shadow_study.db"


def _get_live_listing(package: str, language: str) -> Any:
    credentials = get_app_credentials(package)
    is_app_store = credentials.rc_platform == "app_store"
    if not is_app_store and not credentials.has_play_store():
        raise ProposalDataError(
            f"Play Store credentials are not configured for {package}",
            code="listing_not_live",
        )
    listing = store_listing_client.read_listing(package, language)
    return make_listing_snapshot(
        title=listing.get("title"),
        short_description=listing.get("short_description"),
        full_description=listing.get("full_description"),
        language=language,
        source="app_store_connect_api" if is_app_store else "google_play_developer_api",
        live=True,
    )


async def _shadow_one_app(lifecycle: ExperimentLifecycle, package_name: str) -> dict[str, Any]:
    rulebook_path = PROJECT_ROOT / "rulebooks" / f"{package_name}.yaml"
    if not rulebook_path.is_file():
        return {"app_package": package_name, "status": "skipped", "reason": "no_rulebook"}

    snapshot = get_latest_app_snapshot(DEFAULT_DB_PATH, package_name)
    if not snapshot or not snapshot.get("raw_funnel_json"):
        return {"app_package": package_name, "status": "skipped", "reason": "no_funnel_snapshot"}
    try:
        funnel = json.loads(snapshot["raw_funnel_json"])
    except (TypeError, json.JSONDecodeError):
        return {"app_package": package_name, "status": "skipped", "reason": "unparseable_snapshot"}
    if not isinstance(funnel, dict):
        return {"app_package": package_name, "status": "skipped", "reason": "unparseable_snapshot"}

    captured_at = snapshot.get("data_as_of") or snapshot.get("created_at")
    recommendation = recommend_experiment_designs(
        package_name=package_name,
        funnel=funnel,
        captured_at=captured_at,
        focus="acquisition",
        max_results=5,
    )
    top_aso = next(
        (
            item
            for item in recommendation["recommendations"]
            if item["experiment_type"] == "aso_metadata"
        ),
        None,
    )
    if top_aso is None:
        return {"app_package": package_name, "status": "skipped", "reason": "no_aso_recommendation"}

    try:
        rulebook, rulebook_path = load_rulebook(package_name, project_root=PROJECT_ROOT)
        executable_locale = (
            rulebook.get("executable_locale", EXECUTABLE_LOCALE)
            if isinstance(rulebook, dict)
            else EXECUTABLE_LOCALE
        )
        request = StoreConversionProposalRequest(
            execution_mode="auto_low_risk", language=executable_locale
        )
        current_listing = _get_live_listing(package_name, request.language)
        country_rows = get_country_performance(DEFAULT_DB_PATH, package_name)
        strategy = rulebook.get("aso_strategy", {}) if isinstance(rulebook, dict) else {}
        target_keywords = strategy.get("target_keywords", []) if isinstance(strategy, dict) else []
        generated = ASOClient().generate_optimized_listing(
            package_name=package_name,
            target_keywords=target_keywords if isinstance(target_keywords, list) else [],
            language=request.language.split("-", 1)[0],
            country=request.country.lower(),
        )
        generated_listing = ListingText(
            title=generated.suggested_title,
            short_description=generated.suggested_short_description,
            full_description=generated.suggested_description,
        )
        proposal = build_store_conversion_proposal(
            package=package_name,
            request=request,
            country_rows=country_rows,
            current_listing=current_listing,
            rulebook=rulebook,
            rulebook_source=f"rulebooks/{rulebook_path.name}",
            generated_listing=generated_listing,
        )
    except ProposalDataError as exc:
        return {
            "app_package": package_name,
            "status": "skipped",
            "reason": f"{exc.code}: {exc}",
        }

    created = lifecycle.create_proposal(proposal.lifecycle_payload())
    try:
        advanced = await lifecycle.auto_advance(created["id"])
    except LifecycleError as exc:
        return {
            "app_package": package_name,
            "status": "proposed_only",
            "experiment_id": created["id"],
            "reason": str(exc),
        }

    return {
        "app_package": package_name,
        "status": advanced.get("status"),
        "experiment_id": advanced["id"],
        "hypothesis": advanced.get("hypothesis"),
        "would_have_executed": advanced.get("status") in {"measuring", "concluded"},
        "estimated_monthly_impact": top_aso.get("estimated_monthly_impact"),
    }


async def run_shadow_cycle(db_path: str | Path = SHADOW_DB_PATH) -> dict[str, Any]:
    """Run one shadow PRAO cycle across every app with a rulebook and cached funnel data."""
    lifecycle = build_shadow_lifecycle(db_path)
    apps = _load_apps_config()
    results = []
    for app in apps:
        package_name = app.get("package_name")
        if not package_name:
            continue
        try:
            result = await _shadow_one_app(lifecycle, package_name)
        except Exception as exc:  # one app's failure should not abort the whole cycle
            logger.warning("Shadow cycle failed for app", app=package_name, error=str(exc))
            result = {"app_package": package_name, "status": "error", "reason": str(exc)}
        results.append(result)
    return {"shadow_db_path": str(db_path), "apps": results}


def summarize_shadow_study(db_path: str | Path = SHADOW_DB_PATH) -> dict[str, Any]:
    """Summarize every shadow experiment recorded so far."""
    experiments = get_db_experiments(db_path)
    by_status: dict[str, int] = {}
    for experiment in experiments:
        status = str(experiment.get("status"))
        by_status[status] = by_status.get(status, 0) + 1
    return {
        "shadow_db_path": str(db_path),
        "total_experiments": len(experiments),
        "by_status": by_status,
        "experiments": experiments,
    }


if __name__ == "__main__":
    cycle_result = asyncio.run(run_shadow_cycle())
    print(json.dumps(cycle_result, indent=2, default=str))
    print(json.dumps(summarize_shadow_study(), indent=2, default=str))
