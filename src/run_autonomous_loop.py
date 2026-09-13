"""Scheduler daemon for the autonomous app management loop (Perception-Reasoning-Action-Observation)."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import httpx
import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from analytics_mcp.client import AnalyticsClient
from api_server.routes.portfolio import get_apps_config
from app_manager.credential_store import get_app_credentials
from app_manager.experiment_engine import HypothesisGenerator
from app_manager.experiment_lifecycle import ExperimentLifecycle
from app_store_mcp.client import AppStoreClient
from funnel_engine.db import (
    DEFAULT_DB_PATH,
    finish_sync_run,
    get_db_experiment,
    get_db_experiments,
    get_latest_app_snapshot,
    get_latest_storefront_counts,
    init_db,
    is_emergency_brake_active,
    log_db_action,
    persist_db_experiment_snapshot,
    safe_sync_error,
    save_app_metrics_snapshot,
    set_emergency_brake,
    start_sync_run,
    update_db_experiment_status,
    update_scheduler_heartbeat,
)
from funnel_engine_mcp.server import run_funnel_analysis
from mcp_gc_shared.write_guard import assert_writes_allowed, is_read_only
from play_store_mcp.client import PlayStoreClient
from revenuecat_mcp.client import RevenueCatClient

if TYPE_CHECKING:
    from app_manager.rollback_manager import RollbackManager

# Initialize logger
logger = structlog.get_logger("autonomous_loop")
ROLLBACK_CAPABLE_TOOLS = frozenset({"play_store/update_listing"})


class PostWriteBookkeepingError(RuntimeError):
    """Raised when an external mutation succeeded but local state finalization failed."""


def _scoped_apps(apps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter to AUTONOMOUS_LOOP_PACKAGES (comma-separated) when set; unscoped otherwise."""
    scoped = os.environ.get("AUTONOMOUS_LOOP_PACKAGES", "").strip()
    if not scoped:
        return apps
    packages = {p.strip() for p in scoped.split(",") if p.strip()}
    return [app for app in apps if app.get("package_name") in packages]


def _autonomous_rollback_scope() -> frozenset[str]:
    """Packages explicitly opted into rollback regardless of manual approval status."""
    scoped = os.environ.get("AUTONOMOUS_LOOP_PACKAGES", "").strip()
    return frozenset(p.strip() for p in scoped.split(",") if p.strip())


async def send_telegram_message(text: str, reply_markup: dict[str, Any] | None = None) -> bool:
    """Send a markdown formatted notification to the configured Telegram chat."""
    if is_read_only():
        logger.info("Telegram notification skipped in read-only mode")
        return False
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        logger.warning("Telegram notifications skipped: Token or Chat ID not configured.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload: dict[str, Any] = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(url, json=payload, timeout=10.0)
            return bool(res.status_code == 200)
    except Exception as e:
        logger.exception("Failed to dispatch Telegram notification", error=str(e))
        return False


async def execute_mcp_tool_call(tool_name: str, args: dict[str, Any], app_package: str) -> Any:
    """Execute a write-path tool call dynamically based on tool name."""
    assert_writes_allowed(f"Scheduler tool {tool_name}")
    logger.info("Executing write tool call", tool=tool_name, arguments=args)

    if tool_name == "play_store/update_listing":
        credentials = get_app_credentials(app_package)
        play_client = PlayStoreClient(credentials_path=credentials.google_credentials_path)
        # Clean arg names from camelCase if present
        pkg = args.get("packageName", args.get("package_name", app_package))
        if pkg != app_package:
            raise ValueError("Tool package does not match the experiment app")
        lang = args.get("language", "en-US")
        title = args.get("title")
        short_desc = args.get("shortDescription", args.get("short_description"))
        full_desc = args.get("fullDescription", args.get("full_description"))

        # update_listing logic:
        res = play_client.update_listing(
            package_name=pkg,
            language=lang,
            title=title,
            short_description=short_desc,
            full_description=full_desc,
        )
        return res.model_dump() if hasattr(res, "model_dump") else res

    elif tool_name == "app_store_connect/update_listing":
        credentials = get_app_credentials(app_package)
        app_store_client = AppStoreClient()
        pkg = args.get("packageName", args.get("package_name", app_package))
        if pkg != app_package:
            raise ValueError("Tool package does not match the experiment app")
        lang = args.get("language", "en-US")
        title = args.get("title")
        short_desc = args.get("shortDescription", args.get("short_description"))
        full_desc = args.get("fullDescription", args.get("full_description"))

        res = app_store_client.update_listing(
            bundle_id=pkg,
            title=title,
            short_description=short_desc,
            full_description=full_desc,
            locale=lang,
            profile=credentials.asc_profile,
        )
        return res

    elif tool_name == "revenuecat/create_offering":
        credentials = get_app_credentials(app_package)
        revenuecat_client = RevenueCatClient(
            api_key=credentials.revenuecat_api_key,
            project_id=credentials.revenuecat_project_id,
        )
        project_id = args.get("project_id")
        offering_config = args.get("offering_config", {})
        res = revenuecat_client.create_offering(
            project_id=project_id, offering_config=offering_config
        )
        return res

    else:
        raise ValueError(f"Unsupported tool path: {tool_name}")


async def deploy_approved_experiment(
    experiment: dict[str, Any],
    rollback_manager: RollbackManager,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> tuple[str, dict[str, Any], Any]:
    """Persist rollback state, then perform one approved external mutation."""
    assert_writes_allowed("Scheduler experiment deployment")
    exp_id = experiment["id"]
    package = experiment["app_package"]
    if is_emergency_brake_active(db_path, package):
        raise RuntimeError("Emergency brake blocks writes for this app")
    if experiment["baseline_value"] is None:
        raise RuntimeError("Refusing experiment without a measured baseline")

    args_json = experiment.get("target_args") or experiment.get("snapshot_before")
    args = json.loads(args_json) if args_json else {}
    tool_name = experiment.get("target_tool") or {
        "aso_metadata": "play_store/update_listing",
        "paywall_variant": "revenuecat/create_offering",
    }.get(experiment["experiment_type"])
    if not tool_name:
        raise ValueError(f"No executable tool configured for {experiment['experiment_type']}")
    if tool_name not in ROLLBACK_CAPABLE_TOOLS:
        raise RuntimeError(f"Refusing {tool_name}: no tested automatic rollback is available")

    snapshot = await rollback_manager.capture_snapshot(experiment["experiment_type"], package, args)
    if not snapshot:
        raise RuntimeError("Refusing write because the rollback snapshot could not be captured")
    snapshot_json = json.dumps(snapshot)
    if not persist_db_experiment_snapshot(db_path, exp_id, snapshot_json):
        raise RuntimeError("Failed to persist rollback snapshot")
    if not update_db_experiment_status(db_path, exp_id, "active"):
        raise RuntimeError("Failed to mark experiment active before execution")

    tool_result = await execute_mcp_tool_call(tool_name, args, package)
    if not update_db_experiment_status(
        db_path=db_path,
        exp_id=exp_id,
        status="measuring",
        snapshot_after=json.dumps(tool_result),
    ):
        raise PostWriteBookkeepingError(
            "External write succeeded but experiment bookkeeping failed"
        )
    return tool_name, args, tool_result


async def execute_experiment_rollback(
    experiment: dict[str, Any],
    rollback_manager: RollbackManager,
    result_value: float | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> bool:
    """Execute a rollback and transition state only after external success."""
    assert_writes_allowed("Scheduler experiment rollback")
    try:
        snapshot = json.loads(experiment.get("snapshot_before") or "")
    except (TypeError, json.JSONDecodeError):
        return False
    if not isinstance(snapshot, dict) or not snapshot:
        return False
    succeeded = await rollback_manager.execute_rollback(
        experiment_type=experiment["experiment_type"],
        app_package=experiment["app_package"],
        snapshot_before=snapshot,
    )
    if not succeeded:
        return False
    return update_db_experiment_status(
        db_path=db_path,
        exp_id=experiment["id"],
        status="rolled_back",
        result_value=result_value,
        result_verdict="rolled_back",
    )


async def run_safety_scan() -> None:
    """Lightweight hourly safety scan checking app vitals (crash & ANR rates)."""
    logger.info("Starting hourly safety scan...")
    apps = _scoped_apps(get_apps_config())

    for app in apps:
        package = cast("str", app.get("package_name"))
        display_name = app.get("display_name", app.get("name", package))

        try:
            credentials = get_app_credentials(package)
            if not credentials.has_play_store():
                logger.warning("Skipping safety scan without app credentials", package=package)
                log_db_action(
                    db_path=DEFAULT_DB_PATH,
                    action_type="safety_scan",
                    app_package=package,
                    result="unavailable",
                    reasoning=(
                        "No Play Store credentials -- vitals-based crash/ANR safety "
                        "monitoring is Play Console-only today and does not cover this app."
                    ),
                )
                continue
            play_client = PlayStoreClient(credentials_path=credentials.google_credentials_path)
            vitals = play_client.get_vitals_overview(package)
            crash_rate = vitals.crash_rate
            anr_rate = vitals.anr_rate
            if crash_rate is None or anr_rate is None:
                logger.warning("Safety scan returned no vitals data", package=package)
                log_db_action(
                    db_path=DEFAULT_DB_PATH,
                    action_type="safety_scan",
                    app_package=package,
                    result="unavailable",
                    reasoning="Play Console vitals API returned no crash/ANR data.",
                )
                continue

            # Critical thresholds: crash_rate > 1.0%, anr_rate > 0.47%
            if crash_rate > 1.0 or anr_rate > 0.47:
                reason = f"Crash rate ({crash_rate}%) or ANR ({anr_rate}%) exceeds thresholds"
                logger.error(
                    "Vitals alert triggered!", package=package, crash=crash_rate, anr=anr_rate
                )
                set_emergency_brake(DEFAULT_DB_PATH, package, reason)
                # Log action to DB
                log_db_action(
                    db_path=DEFAULT_DB_PATH,
                    action_type="safety_trigger",
                    app_package=package,
                    result="blocked_by_policy",
                    reasoning=f"CRITICAL: {reason}. Emergency brake active.",
                )
                await send_telegram_message(
                    f"🚨 *Safety Alert / Emergency Brake* 🚨\n"
                    f"App: *{display_name}*\n"
                    f"Crash Rate: `{crash_rate}%` (Threshold: 1.0%)\n"
                    f"ANR Rate: `{anr_rate}%` (Threshold: 0.47%)\n"
                    f"Action: Pausing all active optimization runs and campaigns."
                )
            else:
                log_db_action(
                    db_path=DEFAULT_DB_PATH,
                    action_type="safety_scan",
                    app_package=package,
                    result="ok",
                    reasoning=f"Crash rate {crash_rate}%, ANR rate {anr_rate}% -- within thresholds.",
                )
        except Exception as e:
            logger.exception("Failed safety scan for app", package=package, error=str(e))


async def collect_experiment_observations() -> None:
    """Nightly metrics collector running at 11:00 PM IST."""
    logger.info("Starting nightly experiment observation collection...")
    init_db(DEFAULT_DB_PATH)
    db_exps = get_db_experiments(DEFAULT_DB_PATH)
    scoped_packages = {app["package_name"] for app in _scoped_apps(get_apps_config())}
    active_exps = [
        e
        for e in db_exps
        if e["status"] in ("active", "measuring") and e["app_package"] in scoped_packages
    ]

    if not active_exps:
        logger.info("No active experiments to snapshot.")
        return

    lifecycle = ExperimentLifecycle(DEFAULT_DB_PATH)

    for exp in active_exps:
        package = exp["app_package"]
        metric_key = exp["success_metric"]
        exp_id = exp["id"]

        try:
            if metric_key == "keyword_rank":
                from app_store_mcp.client import AppStoreClient

                evidence = json.loads(exp.get("evidence_json") or "{}")
                baseline = evidence.get("baseline") or {}
                keyword = baseline.get("keyword")
                locale = baseline.get("locale") or "en-US"
                if not keyword:
                    raise ValueError("Experiment evidence has no baseline keyword")
                country = locale.split("-")[-1].lower() if "-" in locale else "us"
                rank_result = AppStoreClient().get_keyword_rank(package, keyword, country=country)
                current_rank = rank_result["rank"]
                observation_date = datetime.now(tz=UTC).strftime("%Y-%m-%d")

                lifecycle.observe(
                    exp_id,
                    rank=current_rank,
                    observed_at=observation_date,
                    period_start=observation_date,
                    period_end=observation_date,
                    source="app_store_search_api",
                    raw_data=rank_result,
                )
                logger.info(
                    "Recorded rank observation",
                    experiment=exp_id,
                    date=observation_date,
                    keyword=keyword,
                    rank=current_rank,
                )
                continue

            if metric_key != "store_view_to_install_rate":
                raise ValueError(f"Metric {metric_key!r} is not supported for observation")
            counts = get_latest_storefront_counts(DEFAULT_DB_PATH, package)
            if counts is None:
                raise ValueError("No measured storefront counts are available")
            visitors = counts["visitors"]
            installs = counts["installs"]
            observation_date = counts["date"]

            lifecycle.observe(
                exp_id,
                visitors=int(visitors),
                installs=int(installs),
                observed_at=observation_date,
                period_start=observation_date,
                period_end=observation_date,
                source="listing_performance_by_country",
                raw_data=counts,
            )
            logger.info(
                "Recorded observation",
                experiment=exp_id,
                date=observation_date,
                visitors=visitors,
                installs=installs,
            )

        except Exception as e:
            logger.exception(
                "Failed to collect observation for experiment", experiment=exp_id, error=str(e)
            )


async def collect_app_snapshots() -> None:
    """Collect and persist metrics snapshots for all apps using per-app credentials.

    This function is the bridge between the agentic layer and the frontend:
    - Agents (this function) call external APIs with per-app credentials.
    - Results are written to app_metrics_snapshots in SQLite.
    - The frontend API reads from SQLite (fast, no external API calls).
    """
    from funnel_engine_mcp.server import (
        _fetch_admob_metrics,
        _fetch_revenuecat_metrics,
        _parse_date_range,
    )

    logger.info("Starting app snapshot collection for all apps...")
    init_db(DEFAULT_DB_PATH)
    apps = _scoped_apps(get_apps_config())
    today_str = datetime.now(tz=UTC).strftime("%Y-%m-%d")

    for app in apps:
        package = cast("str", app.get("package_name"))
        category = app.get("app_category", "utilities")
        try:
            creds = get_app_credentials(package)
            logger.info("Collecting snapshot", app=package, services=creds.get_available_services())
            source_status: dict[str, str] = {}

            # Storefront reports must be ingested before the funnel reads SQLite.
            try:
                from app_manager.storefront_analyst import ingest_latest_month

                storefront_result = await ingest_latest_month(package, db_path=DEFAULT_DB_PATH)
                source_status["storefront"] = storefront_result["status"]
            except Exception as exc:
                source_status["storefront"] = "failure"
                logger.warning(
                    "Storefront ingestion unavailable before snapshot",
                    app=package,
                    error_type=type(exc).__name__,
                )

            # --- Funnel Analysis ---
            funnel_json = None
            funnel_data = {}
            funnel_run_id = start_sync_run(DEFAULT_DB_PATH, "funnel", package)
            try:
                funnel_res = run_funnel_analysis(
                    package_name=package, app_category=category, date_range="30d"
                )
                funnel_data = json.loads(funnel_res)
                funnel_json = funnel_res
                funnel_status = funnel_data.get("status", "success")
                if funnel_status not in {"success", "partial"}:
                    funnel_status = "failure"
                source_status["funnel"] = funnel_status
                finish_sync_run(
                    DEFAULT_DB_PATH,
                    funnel_run_id,
                    funnel_status,
                    record_count=len(funnel_data.get("all_steps") or []),
                    error_safe=(
                        "Required funnel sources unavailable"
                        if funnel_status != "success"
                        else None
                    ),
                )
            except Exception as e:
                source_status["funnel"] = "failure"
                finish_sync_run(
                    DEFAULT_DB_PATH,
                    funnel_run_id,
                    "failure",
                    error_safe=safe_sync_error(e, "Funnel analysis unavailable"),
                )
                logger.warning(
                    "Funnel analysis failed for snapshot",
                    app=package,
                    error_type=type(e).__name__,
                )

            # A failed critical funnel collection must never replace a known-good snapshot.
            if source_status["funnel"] != "success":
                logger.warning(
                    "Preserving prior snapshot because critical funnel data is unavailable",
                    app=package,
                    funnel_status=source_status["funnel"],
                )
                continue

            # --- Revenue (per-app credentials) ---
            admob_metrics = None
            rc_metrics = None
            admob_run_id = start_sync_run(DEFAULT_DB_PATH, "admob", package)
            try:
                if creds.has_admob():
                    from admob_mcp.client import AdMobClient

                    admob_client = AdMobClient(
                        account_id=creds.admob_account_id,
                        credentials_path=creds.google_credentials_path,
                    )
                    admob_metrics = _fetch_admob_metrics(admob_client, package)
                source_status["admob"] = "success" if admob_metrics is not None else "failure"
                finish_sync_run(
                    DEFAULT_DB_PATH,
                    admob_run_id,
                    source_status["admob"],
                    record_count=1 if admob_metrics is not None else 0,
                    error_safe=None if admob_metrics is not None else "AdMob data unavailable",
                )
            except Exception as e:
                source_status["admob"] = "failure"
                finish_sync_run(
                    DEFAULT_DB_PATH,
                    admob_run_id,
                    "failure",
                    error_safe=safe_sync_error(e, "AdMob data unavailable"),
                )
                logger.warning(
                    "AdMob fetch failed for snapshot", app=package, error_type=type(e).__name__
                )

            rc_run_id = start_sync_run(DEFAULT_DB_PATH, "revenuecat", package)
            try:
                if creds.has_revenuecat():
                    rc_client = RevenueCatClient(
                        api_key=creds.revenuecat_api_key,
                        project_id=creds.revenuecat_project_id,
                    )
                    rc_metrics = _fetch_revenuecat_metrics(rc_client, store=creds.rc_platform)
                source_status["revenuecat"] = "success" if rc_metrics is not None else "failure"
                finish_sync_run(
                    DEFAULT_DB_PATH,
                    rc_run_id,
                    source_status["revenuecat"],
                    record_count=1 if rc_metrics is not None else 0,
                    error_safe=None if rc_metrics is not None else "RevenueCat data unavailable",
                )
            except Exception as e:
                source_status["revenuecat"] = "failure"
                finish_sync_run(
                    DEFAULT_DB_PATH,
                    rc_run_id,
                    "failure",
                    error_safe=safe_sync_error(e, "RevenueCat data unavailable"),
                )
                logger.warning(
                    "RevenueCat fetch failed for snapshot",
                    app=package,
                    error_type=type(e).__name__,
                )

            ga4_revenue = None
            analytics_run_id = start_sync_run(DEFAULT_DB_PATH, "analytics_revenue", package)
            try:
                if creds.has_analytics():
                    analytics = AnalyticsClient(
                        property_id=creds.ga4_property_id,
                        credentials_path=creds.google_credentials_path,
                    )
                    start_date, end_date = _parse_date_range("30d")
                    from funnel_engine_mcp.server import _fetch_ga4_revenue

                    ga4_revenue = _fetch_ga4_revenue(analytics, start_date, end_date)
                source_status["analytics_revenue"] = (
                    "success" if ga4_revenue is not None else "failure"
                )
                finish_sync_run(
                    DEFAULT_DB_PATH,
                    analytics_run_id,
                    source_status["analytics_revenue"],
                    record_count=1 if ga4_revenue is not None else 0,
                    error_safe=None if ga4_revenue is not None else "Analytics revenue unavailable",
                )
            except Exception as e:
                source_status["analytics_revenue"] = "failure"
                finish_sync_run(
                    DEFAULT_DB_PATH,
                    analytics_run_id,
                    "failure",
                    error_safe=safe_sync_error(e, "Analytics revenue unavailable"),
                )
                logger.warning(
                    "GA4 revenue fetch failed for snapshot",
                    app=package,
                    error_type=type(e).__name__,
                )

            # --- GCS/App Store IAP Fallback & Google Ads spend ---
            gcs_revenue = None
            if not rc_metrics and creds.gcs_play_console_bucket and creds.google_credentials_path:
                gcs_run_id = start_sync_run(DEFAULT_DB_PATH, "gcs_revenue", package)
                try:
                    from app_manager.gcs_revenue_fetcher import fetch_play_console_revenue

                    gcs_revenue = fetch_play_console_revenue(
                        credentials_path=creds.google_credentials_path,
                        bucket_name=creds.gcs_play_console_bucket,
                        package_name=package,
                        days=30,
                    )
                    source_status["gcs_revenue"] = (
                        "success" if gcs_revenue is not None else "failure"
                    )
                    finish_sync_run(
                        DEFAULT_DB_PATH,
                        gcs_run_id,
                        source_status["gcs_revenue"],
                        record_count=1 if gcs_revenue is not None else 0,
                        error_safe=None if gcs_revenue is not None else "GCS revenue unavailable",
                    )
                except Exception as exc:
                    source_status["gcs_revenue"] = "failure"
                    finish_sync_run(
                        DEFAULT_DB_PATH,
                        gcs_run_id,
                        "failure",
                        error_safe=safe_sync_error(exc, "GCS revenue unavailable"),
                    )
                    logger.warning(
                        "Failed to fetch GCS revenue for snapshot",
                        app=package,
                        error_type=type(exc).__name__,
                    )

            asc_revenue = None
            if not rc_metrics and not gcs_revenue and creds.has_app_store_connect():
                try:
                    from app_manager.app_store_revenue_fetcher import fetch_app_store_revenue

                    ym = datetime.now(UTC).strftime("%Y-%m")
                    asc_revenue = fetch_app_store_revenue(creds, ym)
                except Exception as exc:
                    logger.warning(
                        "Failed to fetch App Store revenue for snapshot",
                        app=package,
                        error=str(exc),
                    )

            google_ads_metrics = None
            google_ads_run_id = start_sync_run(DEFAULT_DB_PATH, "google_ads", package)
            try:
                if creds.has_google_ads() and creds.google_ads_customer_id:
                    from app_manager.google_ads_fetcher import fetch_google_ads_metrics

                    if not creds.google_ads_config_path:
                        raise ValueError("Google Ads config path is missing")
                    google_ads_metrics = (
                        fetch_google_ads_metrics(
                            creds.google_ads_config_path, creds.google_ads_customer_id, 30
                        )
                        or None
                    )
                source_status["google_ads"] = (
                    "success" if google_ads_metrics is not None else "failure"
                )
                finish_sync_run(
                    DEFAULT_DB_PATH,
                    google_ads_run_id,
                    source_status["google_ads"],
                    record_count=1 if google_ads_metrics is not None else 0,
                    error_safe=(
                        None if google_ads_metrics is not None else "Google Ads data unavailable"
                    ),
                )
            except Exception as e:
                source_status["google_ads"] = "failure"
                finish_sync_run(
                    DEFAULT_DB_PATH,
                    google_ads_run_id,
                    "failure",
                    error_safe=safe_sync_error(e, "Google Ads data unavailable"),
                )
                logger.warning(
                    "Google Ads fetch failed for snapshot",
                    app=package,
                    error_type=type(e).__name__,
                )

            # --- Compute aggregate metrics ---
            previous_snapshot = get_latest_app_snapshot(DEFAULT_DB_PATH, package) or {}
            try:
                previous_raw_revenue = json.loads(previous_snapshot.get("raw_revenue_json") or "{}")
            except (TypeError, json.JSONDecodeError):
                previous_raw_revenue = {}
            previous_metric_values = previous_raw_revenue.get("metric_values") or {}
            ad_rev_30d = (
                admob_metrics.get("ad_revenue_30d")
                if admob_metrics is not None
                else previous_snapshot.get("ad_revenue_30d")
            )
            rc_rev_30d = None
            if rc_metrics:
                rc_rev_30d = rc_metrics.get("revenue")
            elif gcs_revenue:
                rc_rev_30d = gcs_revenue.get("iap_revenue_30d")
            elif asc_revenue:
                rc_rev_30d = asc_revenue.get("iap_revenue_30d", 0.0) + asc_revenue.get(
                    "subscription_revenue_30d", 0.0
                )
            else:
                rc_rev_30d = previous_snapshot.get("rc_revenue_30d")

            mrr = previous_snapshot.get("mrr")
            if rc_metrics:
                mrr = rc_metrics.get("mrr")

            subscription_revenue_30d = None
            iap_revenue_30d = None
            if rc_metrics:
                subscription_revenue_30d = rc_metrics.get("revenue")
            elif gcs_revenue:
                iap_revenue_30d = gcs_revenue.get("iap_revenue_30d")
            elif asc_revenue:
                subscription_revenue_30d = asc_revenue.get("subscription_revenue_30d")
                iap_revenue_30d = asc_revenue.get("iap_revenue_30d")
            else:
                subscription_revenue_30d = previous_metric_values.get("subscription_revenue_30d")
                iap_revenue_30d = previous_metric_values.get("iap_revenue_30d")

            total_revenue = (
                (ad_rev_30d or 0.0) + (rc_rev_30d or 0.0)
                if ad_rev_30d is not None or rc_rev_30d is not None
                else previous_snapshot.get("total_revenue_30d")
            )

            current_capture_time = datetime.now(UTC).isoformat()
            try:
                previous_source_status = json.loads(
                    previous_snapshot.get("source_status_json") or "{}"
                )
            except (TypeError, json.JSONDecodeError):
                previous_source_status = {}

            previous_default_time = previous_snapshot.get("data_as_of") or previous_snapshot.get(
                "created_at"
            )

            def source_timestamp(
                source: str,
                statuses: dict[str, Any] = previous_source_status,
                fallback: str | None = previous_default_time,
            ) -> str | None:
                previous = statuses.get(source)
                if isinstance(previous, dict):
                    return previous.get("original_captured_at") or previous.get("captured_at")
                return fallback

            def source_detail(
                source: str,
                *,
                status: str = "success",
                captured_at: str | None = current_capture_time,
                carried_forward: bool = False,
            ) -> dict[str, Any]:
                return {
                    "source": source,
                    "status": status,
                    "captured_at": captured_at,
                    "original_captured_at": captured_at,
                    "carried_forward": carried_forward,
                }

            def carried_metric_detail(
                metric: str,
                fallback_source: str,
                statuses: dict[str, Any] = previous_source_status,
            ) -> dict[str, Any]:
                previous = statuses.get(metric)
                original_timestamp = source_timestamp(metric)
                original_source = fallback_source
                if isinstance(previous, dict):
                    original_source = str(previous.get("source") or fallback_source)
                return source_detail(
                    original_source,
                    status="carried_forward",
                    captured_at=original_timestamp,
                    carried_forward=True,
                )

            source_details: dict[str, dict[str, Any]] = {
                source: source_detail(source, status=status)
                for source, status in source_status.items()
            }
            if admob_metrics is None and previous_snapshot.get("ad_revenue_30d") is not None:
                source_details["admob"] = carried_metric_detail("ad_revenue", "admob")

            if admob_metrics is not None:
                source_details["ad_revenue"] = source_detail("admob")
            elif previous_snapshot.get("ad_revenue_30d") is not None:
                source_details["ad_revenue"] = carried_metric_detail("ad_revenue", "admob")
            else:
                source_details["ad_revenue"] = source_detail(
                    "admob", status="unavailable", captured_at=None
                )

            if rc_metrics is not None:
                source_details["subscription_revenue"] = source_detail("revenuecat")
                source_details["mrr"] = source_detail("revenuecat")
            else:
                if previous_snapshot.get("mrr") is not None:
                    source_details["mrr"] = carried_metric_detail("mrr", "revenuecat")
                else:
                    source_details["mrr"] = source_detail(
                        "revenuecat", status="unavailable", captured_at=None
                    )

                if gcs_revenue is not None:
                    source_details["iap_revenue"] = source_detail("gcs_revenue")
                elif asc_revenue is not None:
                    if asc_revenue.get("iap_revenue_30d") is not None:
                        source_details["iap_revenue"] = source_detail("app_store")
                    if asc_revenue.get("subscription_revenue_30d") is not None:
                        source_details["subscription_revenue"] = source_detail("app_store")
                elif previous_snapshot.get("rc_revenue_30d") is not None:
                    previous_metric_keys = {
                        key
                        for key in ("subscription_revenue", "iap_revenue")
                        if isinstance(previous_source_status.get(key), dict)
                    }
                    if previous_metric_keys:
                        for key in previous_metric_keys:
                            source_details[key] = carried_metric_detail(key, key)
                    else:
                        source_details["revenue_aggregate"] = carried_metric_detail(
                            "revenue_aggregate", "unknown_revenue_source"
                        )

            # Extract funnel health from analysis
            health_score = funnel_data.get("funnel_health_score")
            top_leak = (funnel_data.get("leaks") or [None])[0]
            top_leak_name = top_leak.get("name") if top_leak else None
            top_leak_value = top_leak.get("conversion_rate") if top_leak else None
            top_leak_bench = top_leak.get("benchmark_rate") if top_leak else None

            # Active users from funnel data
            active_users = funnel_data.get("real_event_mapping", {}).get("total_30d_users", 0)
            d1_ret = (
                funnel_data.get("retention", {}).get("d1_retention_rate", 0)
                if isinstance(funnel_data.get("retention"), dict)
                else 0
            )
            d7_ret = (
                funnel_data.get("retention", {}).get("d7_retention_rate", 0)
                if isinstance(funnel_data.get("retention"), dict)
                else 0
            )

            # Build install sparkline (from storefront DB if available)
            installs_7d = "[]"
            try:
                from funnel_engine.db import get_db_connection

                conn = get_db_connection(DEFAULT_DB_PATH)
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT date, SUM(installs) as daily_installs
                    FROM listing_performance_by_country
                    WHERE package_name = ?
                    GROUP BY date
                    ORDER BY date DESC
                    LIMIT 7;
                    """,
                    (package,),
                )
                rows = cursor.fetchall()
                conn.close()
                if rows:
                    installs_7d = json.dumps([r["daily_installs"] for r in reversed(rows)])
            except Exception as exc:
                logger.warning("Failed to load install history", app=package, error=str(exc))

            # Revenue JSON for raw storage
            revenue_json = json.dumps(
                {
                    "admob": admob_metrics,
                    "revenuecat": rc_metrics,
                    "gcs_iap": gcs_revenue,
                    "app_store": asc_revenue,
                    "ga4": ga4_revenue,
                    "google_ads": google_ads_metrics,
                    "metric_values": {
                        "ad_revenue_30d": ad_rev_30d,
                        "subscription_revenue_30d": subscription_revenue_30d,
                        "iap_revenue_30d": iap_revenue_30d,
                        "mrr": mrr,
                    },
                    "source_status": source_details,
                }
            )

            # --- Save snapshot ---
            save_app_metrics_snapshot(
                db_path=DEFAULT_DB_PATH,
                package_name=package,
                snapshot_date=today_str,
                metrics={
                    "funnel_health_score": health_score,
                    "top_leak_name": top_leak_name,
                    "top_leak_value": top_leak_value,
                    "top_leak_benchmark": top_leak_bench,
                    "mrr": mrr,
                    "mrr_change_pct": 0,  # TODO: compute from previous snapshot
                    "ad_revenue_30d": ad_rev_30d,
                    "rc_revenue_30d": rc_rev_30d,
                    "total_revenue_30d": total_revenue,
                    "installs_7d": installs_7d,
                    "active_users_30d": active_users,
                    "d1_retention": d1_ret,
                    "d7_retention": d7_ret,
                    "raw_funnel_json": funnel_json,
                    "raw_revenue_json": revenue_json,
                    "source_status_json": json.dumps(source_details),
                    "data_as_of": current_capture_time,
                    "is_partial": any(
                        detail["status"] != "success" for detail in source_details.values()
                    ),
                },
            )
            logger.info("Snapshot saved", app=package, health=health_score, revenue=total_revenue)
            log_db_action(
                db_path=DEFAULT_DB_PATH,
                action_type="snapshot_collect",
                app_package=package,
                result="success",
                reasoning=(
                    f"Funnel health {health_score}, total revenue (30d) {total_revenue}, "
                    f"sources: {json.dumps(source_status)}"
                ),
            )

        except Exception as e:
            logger.exception("Failed to collect snapshot for app", app=package, error=str(e))
            log_db_action(
                db_path=DEFAULT_DB_PATH,
                action_type="snapshot_collect",
                app_package=package,
                result="failure",
                reasoning=safe_sync_error(e, "Snapshot collection failed"),
            )

    logger.info("App snapshot collection complete.")


async def _apply_automatic_disposition(
    lifecycle: ExperimentLifecycle,
    experiment: dict[str, Any],
    evaluation: dict[str, Any],
    validation: dict[str, Any],
    *,
    allow_manual_rollback: bool = False,
) -> None:
    """Apply only policy-authorized automatic terminal experiment actions.

    Auto-retaining a winner always requires true auto_low_risk authority --
    that's an autonomy escalation this loop doesn't grant on its own.
    Rolling back a degrading experiment is a safety action, not an autonomy
    escalation, so apps explicitly named in AUTONOMOUS_LOOP_PACKAGES
    (allow_manual_rollback=True) get it even when the initial deploy required
    manual/Telegram approval -- deploy and rollback are deliberately gated
    differently.
    """
    if is_read_only():
        return
    is_auto_low_risk = (
        experiment.get("execution_mode") == "auto_low_risk"
        and experiment.get("approved_via") == "auto_low_risk"
        and validation.get("valid") is True
        and validation.get("effective_execution_mode") == "auto_low_risk"
    )

    verdict = evaluation["verdict"]
    if verdict == "winner" and is_auto_low_risk:
        lifecycle.retain(
            experiment["id"],
            actor="scheduler",
            reason="Auto-retained statistically significant winner",
        )
    elif verdict == "rollback" and (is_auto_low_risk or allow_manual_rollback):
        await lifecycle.rollback(
            experiment["id"],
            actor="scheduler",
            reason=f"Automatic rollback disposition: {evaluation['reason']}",
        )


async def _run_prao_cycle_impl() -> None:
    """Daily Perception-Reasoning-Action-Observation cycle (6:00 AM IST)."""
    logger.info("Starting daily PRAO cycle...")
    init_db(DEFAULT_DB_PATH)

    # ═══ STEP 0: Collect metrics snapshots for all apps ═══
    await collect_app_snapshots()

    apps = _scoped_apps(get_apps_config())
    generator = HypothesisGenerator()
    lifecycle = ExperimentLifecycle(DEFAULT_DB_PATH)

    for app in apps:
        package = cast("str", app.get("package_name"))
        display_name = app.get("display_name", app.get("name", package))
        category = app.get("app_category", "utilities")

        # ═══ PERCEPTION ═══
        logger.info("PRAO Step 1: Perception", app=package)
        try:
            funnel_res = run_funnel_analysis(
                package_name=package, app_category=category, date_range="30d"
            )
            funnel_snapshot = json.loads(funnel_res)
        except Exception as e:
            logger.exception("Funnel fetch failed", app=package, error=str(e))
            continue

        # ═══ REASONING (Evaluate active experiments) ═══
        logger.info("PRAO Step 2: Reasoning", app=package)
        try:
            db_exps = get_db_experiments(DEFAULT_DB_PATH, app_package=package)
        except Exception as e:
            logger.exception("Failed loading experiments from DB", error=str(e))
            db_exps = []

        active_exps = [e for e in db_exps if e["status"] in ("active", "measuring")]

        for exp in active_exps:
            exp_id = exp["id"]
            try:
                evaluation = lifecycle.evaluate(exp_id)
                verdict = evaluation["verdict"]
                logger.info(
                    "Experiment evaluation result",
                    id=exp_id,
                    verdict=verdict,
                    change=evaluation["observed_change"],
                )
                validation = lifecycle.current_policy_validation(exp_id)
                await _apply_automatic_disposition(
                    lifecycle,
                    exp,
                    evaluation,
                    validation,
                    allow_manual_rollback=package in _autonomous_rollback_scope(),
                )
                if verdict not in {"insufficient_data"}:
                    await send_telegram_message(
                        f"📊 *Experiment Evaluated* 📊\n"
                        f"App: *{display_name}*\n"
                        f"Verdict: *{verdict.upper()}*\n"
                        f"Confidence: `{evaluation['confidence']:.1%}`\n"
                        f"Change: `{evaluation['observed_change']:+.1%}`\n"
                        f"Details: {evaluation['reason']}"
                    )
            except Exception as e:
                logger.exception("Failed lifecycle evaluation", experiment=exp_id, error=str(e))

        # ═══ HYPOTHESIS GENERATION ═══
        logger.info("PRAO Step 3: Hypothesis Generation", app=package)
        active_count = len([e for e in db_exps if e["status"] in ("active", "measuring")])
        rulebook_path = Path("rulebooks") / f"{package}.yaml"
        rulebook = {}
        if rulebook_path.exists():
            import yaml

            with rulebook_path.open() as f:
                rulebook = yaml.safe_load(f)

        max_concurrent = rulebook.get("max_concurrent", 2)

        if active_count < max_concurrent:
            # Query current benchmarks
            from funnel_engine.benchmarks import get_benchmarks

            bench = get_benchmarks(category)

            # Generate hypothesis via Gemini
            res = await generator.generate(
                app_package=package,
                funnel_snapshot=funnel_snapshot,
                benchmarks=bench,
                active_experiments=[
                    dict(e) for e in db_exps if e["status"] in ("active", "measuring")
                ],
                rulebook=rulebook,
                trust_tier="moderate",  # standard trust tier
            )

            if res and "proposed_experiment" in res:
                prop = res["proposed_experiment"]
                try:
                    from app_manager.store_conversion_proposals import (
                        ListingText,
                        build_keyword_rank_proposal,
                        make_listing_snapshot,
                    )

                    target_args = prop.get("target_args") or {}
                    current_listing = make_listing_snapshot(
                        title=display_name,
                        short_description="Pomodoro & Focus Timer",
                        full_description="Focus timer and pomodoro app.",
                        language=str(target_args.get("language") or "en-GB"),
                        source="itunes_lookup",
                        live=True,
                    )
                    proposed_text = ListingText(
                        title=str(target_args.get("title") or "Pomodori: Study Pomodoro Timer"),
                        short_description=str(
                            target_args.get("shortDescription") or "Study Timer & Break Planner"
                        ),
                    )
                    payload = build_keyword_rank_proposal(
                        package=package,
                        current_listing=current_listing,
                        proposed_listing=proposed_text,
                        keyword="pomodoro",
                        current_rank=None,
                        language=str(target_args.get("language") or "en-GB"),
                        rulebook=rulebook,
                        rulebook_source=f"rulebooks/{package}.yaml",
                        target_tool=str(
                            prop.get("target_tool") or "app_store_connect/update_listing"
                        ),
                    )
                    created_exp = lifecycle.create_proposal(payload)
                    exp_id = created_exp["id"]

                    reply_markup = {
                        "inline_keyboard": [
                            [
                                {"text": "✅ Approve & Deploy", "callback_data": f"appr_{exp_id}"},
                                {"text": "❌ Reject", "callback_data": f"rjct_{exp_id}"},
                            ]
                        ]
                    }

                    await send_telegram_message(
                        f"💡 *New Experiment Proposed* 💡\n"
                        f"App: *{display_name}*\n"
                        f"Hypothesis: {prop.get('hypothesis')}\n"
                        f"Expected Impact: {res.get('expected_impact')}\n"
                        f"Risk: {res.get('risk_assessment')}\n"
                        f"Type: `{prop.get('experiment_type')}`\n\n"
                        f'👉 *Tap Approve & Deploy below* or reply *"make changes"* to execute!',
                        reply_markup=reply_markup,
                    )
                except Exception as exc:
                    logger.exception("Failed to build canonical proposal", error=str(exc))
                    await send_telegram_message(
                        f"💡 *New Experiment Proposed* 💡\n"
                        f"App: *{display_name}*\n"
                        f"Hypothesis: {prop.get('hypothesis')}\n"
                        f"Expected Impact: {res.get('expected_impact')}\n"
                        f"Risk: {res.get('risk_assessment')}\n"
                        f"Type: `{prop.get('experiment_type')}`"
                    )

        # ═══ ACTIONS (Deploy approved experiments) ═══
        logger.info("PRAO Step 4: Actions", app=package)
        if is_read_only():
            logger.info("Read-only mode skips automatic experiment dispositions and writes")
            continue
        approved_queue = [
            experiment
            for experiment in db_exps
            if experiment["status"] == "approved"
            and experiment.get("execution_mode") == "auto_low_risk"
            and json.loads(experiment.get("validation_json") or "{}").get(
                "effective_execution_mode"
            )
            == "auto_low_risk"
        ]
        if is_emergency_brake_active(DEFAULT_DB_PATH, package):
            logger.warning("Emergency brake blocks PRAO writes", app=package)
            continue

        for exp in approved_queue:
            exp_id = exp["id"]
            try:
                await lifecycle.execute(exp_id)
                await send_telegram_message(
                    f"🚀 *Experiment Started* 🚀\n"
                    f"App: *{display_name}*\n"
                    f"Experiment *{exp_id}* is now active.\n"
                    f"Metric: `{exp['success_metric']}`\n"
                    f"Baseline: `{exp['baseline_value']}`"
                )
            except Exception as e:
                logger.exception(
                    "Failed to execute approved experiment", experiment=exp_id, error=str(e)
                )


async def run_prao_cycle() -> None:
    """Run one PRAO cycle while durably publishing its lifecycle."""
    update_scheduler_heartbeat(DEFAULT_DB_PATH, cycle_event="started")
    try:
        await _run_prao_cycle_impl()
    except Exception as exc:
        update_scheduler_heartbeat(
            DEFAULT_DB_PATH,
            cycle_event="failure",
            error_safe=safe_sync_error(exc, "PRAO cycle failed"),
        )
        raise
    update_scheduler_heartbeat(DEFAULT_DB_PATH, cycle_event="success")


_telegram_offset = 0


async def _prime_telegram_offset() -> None:
    """Skip any pre-existing Telegram backlog on startup rather than replaying it.

    _telegram_offset resets to 0 on every process restart. Without priming,
    a crash-and-restart (KeepAlive) would re-fetch and re-act on any old,
    still-unconfirmed updates -- including a stale "approve" from days
    earlier. This does one no-op getUpdates call to fast-forward past
    whatever is already sitting in the queue before polling starts for real.
    """
    global _telegram_offset
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        return
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(
                f"https://api.telegram.org/bot{token}/getUpdates",
                params={"timeout": 1},
                timeout=5.0,
            )
            if res.status_code != 200:
                return
            data = res.json()
            updates = data.get("result") or []
            if updates:
                _telegram_offset = max(u["update_id"] for u in updates) + 1
                logger.info(
                    "Skipped existing Telegram backlog on startup",
                    skipped_updates=len(updates),
                    new_offset=_telegram_offset,
                )
    except Exception as e:
        logger.warning("Failed to prime Telegram offset on startup", error=str(e))


def _stuck_active_note(exp_id: str) -> str:
    """Explain, rather than silently hide, an experiment left in the unrecoverable

    "active" state after a write raised mid-flight. ExperimentLifecycle.execute()
    refuses to retry an "active" experiment (see experiment_lifecycle.py) --
    it needs a rollback or manual reconciliation, not another approve/execute.
    """
    exp = get_db_experiment(DEFAULT_DB_PATH, exp_id)
    if exp and exp.get("status") == "active":
        return (
            "\nThis experiment is now stuck in an in-flight write state and "
            "*cannot be retried automatically* -- it needs a rollback or manual "
            "reconciliation before trying again."
        )
    return ""


async def check_and_process_telegram_approvals() -> None:
    """Poll Telegram for user approval responses (inline buttons or 'make changes' / 'approve' messages)."""
    global _telegram_offset
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return

    url = f"https://api.telegram.org/bot{token}/getUpdates"
    params: dict[str, Any] = {"timeout": 1}
    if _telegram_offset > 0:
        params["offset"] = _telegram_offset

    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(url, params=params, timeout=5.0)
            if res.status_code != 200:
                return
            data = res.json()
            if not data.get("ok") or not data.get("result"):
                return

            lifecycle = ExperimentLifecycle(DEFAULT_DB_PATH)
            for update in data["result"]:
                _telegram_offset = max(_telegram_offset, update["update_id"] + 1)

                # 1. Handle inline button callback
                callback = update.get("callback_query")
                if callback:
                    cb_data = str(callback.get("data", ""))
                    query_id = callback.get("id")
                    if cb_data.startswith("appr_"):
                        exp_id = cb_data[5:]
                        try:
                            lifecycle.approve(
                                exp_id,
                                actor="telegram:user",
                                reason="Approved via Telegram inline button",
                            )
                            await lifecycle.execute(exp_id)
                            await client.post(
                                f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                                json={
                                    "callback_query_id": query_id,
                                    "text": "Approved & Executed!",
                                },
                            )
                            await send_telegram_message(
                                f"🟢 *Status: Approved & Deployed to App Store!* 🚀\n"
                                f"Experiment `{exp_id}` is now active."
                            )
                        except Exception as e:
                            logger.exception(
                                "Failed to execute approved experiment from Telegram callback",
                                error=str(e),
                            )
                            await send_telegram_message(
                                f"⚠️ *Approval Error:* {e}{_stuck_active_note(exp_id)}"
                            )

                    elif cb_data.startswith("rjct_"):
                        exp_id = cb_data[5:]
                        try:
                            lifecycle.reject(
                                exp_id,
                                actor="telegram:user",
                                reason="Rejected via Telegram inline button",
                            )
                            await client.post(
                                f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                                json={"callback_query_id": query_id, "text": "Proposal Rejected"},
                            )
                            await send_telegram_message("🔴 *Status: Proposal Rejected.*")
                        except Exception as e:
                            logger.exception(
                                "Failed to reject experiment from Telegram callback", error=str(e)
                            )

                # 2. Handle text message ("make changes", "approve", "yes", "deploy")
                msg = update.get("message")
                if msg and "text" in msg:
                    text_lower = str(msg.get("text", "")).strip().lower()
                    if any(
                        cmd in text_lower
                        for cmd in ("make changes", "approve", "deploy", "go ahead", "yes")
                    ):
                        db_exps = get_db_experiments(DEFAULT_DB_PATH)
                        proposed = [e for e in db_exps if e["status"] == "proposed"]
                        if proposed:
                            target_exp = proposed[0]
                            exp_id = target_exp["id"]
                            try:
                                lifecycle.approve(
                                    exp_id,
                                    actor="telegram:user",
                                    reason="Approved via Telegram text message",
                                )
                                await lifecycle.execute(exp_id)
                                await send_telegram_message(
                                    f"🟢 *Status: Approved & Deployed to App Store!* 🚀\n"
                                    f"Experiment `{exp_id}` for `{target_exp['app_package']}` is now active."
                                )
                            except Exception as e:
                                logger.exception(
                                    "Failed to execute experiment from text command", error=str(e)
                                )
                                await send_telegram_message(
                                    f"⚠️ *Approval/Deploy Error:* {e}{_stuck_active_note(exp_id)}"
                                )
                        else:
                            await send_telegram_message(
                                "📋 No proposed experiments currently pending approval."
                            )
                    elif any(cmd in text_lower for cmd in ("reject", "cancel", "no")):
                        db_exps = get_db_experiments(DEFAULT_DB_PATH)
                        proposed = [e for e in db_exps if e["status"] == "proposed"]
                        if proposed:
                            target_exp = proposed[0]
                            exp_id = target_exp["id"]
                            try:
                                lifecycle.reject(
                                    exp_id,
                                    actor="telegram:user",
                                    reason="Rejected via Telegram text message",
                                )
                                await send_telegram_message(
                                    f"🔴 *Status: Proposal `{exp_id}` Rejected.*"
                                )
                            except Exception as e:
                                logger.exception(
                                    "Failed to reject experiment from text command", error=str(e)
                                )

    except Exception as e:
        logger.warning("Telegram approval polling error", error=str(e))


def publish_scheduler_heartbeat() -> None:
    """Refresh scheduler liveness for the system status API."""
    update_scheduler_heartbeat(DEFAULT_DB_PATH)


def start_scheduler() -> None:
    """Initialize APScheduler daemon and register cron triggers."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    scheduler = AsyncIOScheduler(event_loop=loop)
    init_db(DEFAULT_DB_PATH)
    update_scheduler_heartbeat(DEFAULT_DB_PATH, process_started=True)

    # 1. Daily PRAO cycle — runs at 6:00 AM IST
    scheduler.add_job(
        run_prao_cycle,
        CronTrigger(hour=6, minute=0, timezone="Asia/Kolkata"),
        id="daily_prao",
        misfire_grace_time=3600,
    )

    # 2. Hourly safety check — lightweight vitals/crash rate scan
    scheduler.add_job(run_safety_scan, CronTrigger(minute=0), id="hourly_safety")

    # 3. Experiment observation collector — runs at 11:00 PM IST
    scheduler.add_job(
        collect_experiment_observations,
        CronTrigger(hour=23, minute=0, timezone="Asia/Kolkata"),
        id="nightly_observations",
    )

    # Skip any pre-existing Telegram backlog before the listener starts polling for real.
    loop.run_until_complete(_prime_telegram_offset())

    # 4. Telegram approval listener — polls every 10 seconds for user text/button approvals
    scheduler.add_job(
        check_and_process_telegram_approvals,
        IntervalTrigger(seconds=10),
        id="telegram_approvals",
        max_instances=1,
    )

    scheduler.add_job(
        publish_scheduler_heartbeat,
        IntervalTrigger(minutes=1),
        id="scheduler_heartbeat",
        max_instances=1,
    )

    logger.info("Autonomous Loop Scheduler initialized. Starting daemon...")
    scheduler.start()

    # Keep the event loop running
    try:
        loop.run_forever()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler daemon shut down.")
    finally:
        scheduler.shutdown(wait=False)
        loop.close()


if __name__ == "__main__":
    start_scheduler()
