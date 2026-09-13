"""MCP server for Funnel Analysis Engine."""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import structlog
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from analytics_mcp.client import AnalyticsClient
from funnel_engine.analyzer import FunnelAnalyzer
from play_store_mcp.client import PlayStoreClient
from revenuecat_mcp.client import RevenueCatClient, RevenueCatClientError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from admob_mcp.client import AdMobClient
    from play_store_mcp.models import AppDetails

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[None]:  # noqa: ARG001
    """Initialize environment before server starts."""
    load_dotenv(override=True)
    yield


mcp = FastMCP("funnel-engine-mcp", lifespan=lifespan)
analyzer = FunnelAnalyzer()


def _demo_mode() -> bool:
    """Return whether explicitly enabled synthetic demo data may be used."""
    return os.environ.get("MCP_GC_DEMO_MODE") == "1"


def _unavailable_funnel(
    package_name: str,
    date_range: str,
    unavailable_sources: list[str],
    *,
    status: str = "unavailable",
) -> str:
    """Build a contract-compatible response without inventing measurements."""
    captured_at = datetime.now(UTC).isoformat()
    return json.dumps(
        {
            "status": status,
            "app_id": package_name,
            "analysis_date": captured_at,
            "period": date_range,
            "funnel_health_score": None,
            "total_monthly_revenue_impact": None,
            "leaks": [],
            "ranked_leaks": [],
            "all_steps": [],
            "data_sources": [],
            "unavailable_sources": unavailable_sources,
            "summary": "Funnel analysis is unavailable because required observed sources are missing.",
            "provenance": {
                "source": "funnel_engine",
                "captured_at": captured_at,
                "period": date_range,
                "is_live": False,
            },
        },
        indent=2,
    )


def _get_analytics_client() -> AnalyticsClient:
    return AnalyticsClient()


def _get_play_store_client() -> PlayStoreClient:
    return PlayStoreClient()


def _get_revenuecat_client() -> RevenueCatClient | None:
    try:
        return RevenueCatClient()
    except RevenueCatClientError as e:
        logger.warning(
            "RevenueCat client initialization failed. Continuing without RevenueCat data.",
            error=str(e),
        )
        return None


def _get_admob_client() -> AdMobClient | None:
    """Try to create AdMob client, return None if credentials are missing."""
    try:
        from admob_mcp.client import AdMobClient

        return AdMobClient()
    except Exception as e:
        logger.warning(
            "AdMob client initialization failed. Continuing without AdMob data.",
            error=str(e),
        )
        return None


def _parse_date_range(date_range: str) -> tuple[str, str]:
    """Parse date_range (e.g. '30d') into (start_date, end_date) format for AnalyticsClient."""
    start_date = "30daysAgo"
    if date_range.endswith("d"):
        try:
            days = int(date_range[:-1])
            start_date = f"{days}daysAgo"
        except ValueError:
            pass
    elif "ago" in date_range.lower():
        start_date = date_range
    return start_date, "today"


def _parse_date_range_iso(date_range: str) -> tuple[str, str]:
    """Parse date_range into ISO dates (YYYY-MM-DD) for AdMob API."""
    from datetime import UTC, datetime, timedelta

    now = datetime.now(tz=UTC)
    days = 30
    if date_range.endswith("d"):
        with suppress(ValueError):
            days = int(date_range[:-1])
    start = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    end = now.strftime("%Y-%m-%d")
    return start, end


def _get_installs(ga4_events: Any, ga4_active: Any) -> int:
    """Get observed install count from GA4 first_open events."""
    installs = 0
    if hasattr(ga4_events, "events"):
        for ev in ga4_events.events:
            name = ev.get("event_name") if isinstance(ev, dict) else getattr(ev, "event_name", "")
            if name == "first_open":
                installs = cast(
                    "int",
                    ev.get("total_users")
                    if isinstance(ev, dict)
                    else getattr(ev, "total_users", 0),
                )
                if not installs:
                    installs = cast(
                        "int",
                        ev.get("event_count")
                        if isinstance(ev, dict)
                        else getattr(ev, "event_count", 0),
                    )
                break
    if installs <= 0 and _demo_mode() and ga4_active and hasattr(ga4_active, "total_users"):
        installs = ga4_active.total_users
    if installs <= 0 and _demo_mode():
        return 1000
    return installs if installs > 0 else 0


def _get_ga4_event_counts(ga4_events: Any) -> dict[str, int]:
    """Extract a {event_name: user_count} dict from GA4 events response."""
    events_raw = {}
    if hasattr(ga4_events, "events"):
        for ev in ga4_events.events:
            name = cast(
                "str",
                ev.get("event_name") if isinstance(ev, dict) else getattr(ev, "event_name", ""),
            )
            users = cast(
                "int",
                ev.get("total_users") if isinstance(ev, dict) else getattr(ev, "total_users", 0),
            )
            events_raw[name] = users
    return events_raw


def _calculate_real_retention(ga4_retention: Any) -> tuple[float, float, float]:
    """
    Calculate actual retention rates from GA4 RetentionReport cohorts.

    The GA4 retention cohorts have: new_users (cohort_size) and returning_users.
    We compute overall retention rate from these.
    """
    if not ga4_retention or not hasattr(ga4_retention, "cohorts"):
        return 0.0, 0.0, 0.0

    cohorts = ga4_retention.cohorts
    if not cohorts:
        return 0.0, 0.0, 0.0

    # GA4 retention API returns daily cohorts; each cohort has new_users and returning_users
    # Overall retention rate = sum(returning_users) / sum(new_users)
    total_new = sum(
        c.get("new_users", 0) if isinstance(c, dict) else getattr(c, "new_users", 0)
        for c in cohorts
    )
    total_returning = sum(
        c.get("returning_users", 0) if isinstance(c, dict) else getattr(c, "returning_users", 0)
        for c in cohorts
    )

    overall_rate = total_returning / total_new if total_new > 0 else 0.0

    # For daily retention (D1, D7, D30), we approximate since the API gives us
    # returning users over the full period. Scale based on industry patterns.
    # Typical relationship: D1 ≈ overall_rate * 0.30, D7 ≈ overall_rate * 0.15, D30 ≈ overall_rate * 0.08
    # But if overall_rate is very high (like 97%), it's likely the "returning" ratio is DAU/MAU style
    if overall_rate > 0.5:
        # This is a DAU/MAU type metric - high returning user ratio
        # Scale down to D1/D7/D30 industry-standard ranges
        d1 = min(0.45, overall_rate * 0.35)
        d7 = min(0.25, overall_rate * 0.18)
        d30 = min(0.12, overall_rate * 0.10)
    else:
        d1 = overall_rate * 0.8
        d7 = overall_rate * 0.5
        d30 = overall_rate * 0.3

    return d1, d7, d30


def _prepare_play_store_details(
    store_details: Any,
    installs: int,
    app_category: str,
    package_name: str,
    days: int = 30,
) -> dict[str, Any]:
    """Convert AppDetails model to dictionary and enrich with storefront metrics (from GCS DB if available)."""
    details_dict = (
        store_details.model_dump() if hasattr(store_details, "model_dump") else dict(store_details)
    )

    from app_manager.storefront_analyst import DEFAULT_DB_PATH
    from funnel_engine.benchmarks import get_benchmarks
    from funnel_engine.db import get_total_impressions, get_total_storefront_metrics

    benchmarks = get_benchmarks(app_category)
    details_dict["benchmark_conversion_rate"] = benchmarks.get("store_conversion_rate", 0.33)

    real_metrics = get_total_storefront_metrics(DEFAULT_DB_PATH, package_name, days)
    if real_metrics and real_metrics.get("visitors", 0) > 0:
        details_dict["store_visitors"] = real_metrics["visitors"]
        details_dict["installs"] = real_metrics["installs"]

        # Real per-day impressions (App Store Connect analytics ingestion only,
        # see asc_analytics_ingest.py) take priority over the benchmark estimate.
        real_impressions = get_total_impressions(DEFAULT_DB_PATH, package_name, days)
        if real_impressions and real_impressions > 0:
            details_dict["store_impressions"] = real_impressions
            impressions_quality = "observed"
        else:
            imp_to_view = benchmarks.get("impression_to_store_view", 0.35)
            details_dict["store_impressions"] = (
                int(real_metrics["visitors"] / imp_to_view)
                if imp_to_view > 0
                else real_metrics["visitors"]
            )
            impressions_quality = "estimated"
        details_dict["top_funnel_estimated"] = False
        details_dict["metric_quality"] = {
            "store_impressions": impressions_quality,
            "store_visitors": "observed",
            "installs": "observed",
        }
        details_dict["source"] = "listing_performance_by_country"
        logger.info(
            "Using real storefront metrics from SQLite database",
            package_name=package_name,
            visitors=real_metrics["visitors"],
            installs=real_metrics["installs"],
            days=days,
        )
    elif _demo_mode():
        # Fallback to category benchmarks
        store_conv = benchmarks.get("store_conversion_rate", 0.33)
        imp_to_view = benchmarks.get("impression_to_store_view", 0.35)

        store_visitors = int(installs / store_conv) if store_conv > 0 else installs
        store_impressions = int(store_visitors / imp_to_view) if imp_to_view > 0 else store_visitors

        details_dict["store_impressions"] = store_impressions
        details_dict["store_visitors"] = store_visitors
        details_dict["installs"] = installs
        details_dict["top_funnel_estimated"] = True
        details_dict["metric_quality"] = {
            "store_impressions": "estimated",
            "store_visitors": "estimated",
            "installs": "estimated",
        }
        details_dict["source"] = "demo_category_benchmark"
    else:
        details_dict["store_impressions"] = None
        details_dict["store_visitors"] = None
        details_dict["installs"] = None
        details_dict["top_funnel_estimated"] = False
        details_dict["metric_quality"] = {
            "store_impressions": "unavailable",
            "store_visitors": "unavailable",
            "installs": "unavailable",
        }
        details_dict["source"] = "unavailable"

    return details_dict


def _fetch_admob_metrics(
    admob_client: AdMobClient | None, package_name: str
) -> dict[str, Any] | None:
    """Fetch real AdMob revenue and impression data."""
    if not admob_client:
        return None

    try:
        from admob_mcp.mappings import get_app_id_for_package

        # Try to resolve app ID using mappings first
        app_id = get_app_id_for_package(
            package_name,
            publisher_id=admob_client._account_id,  # noqa: SLF001
        )

        if not app_id:
            # Fallback to store id matching
            apps = admob_client.list_apps()
            for app in apps:
                if app.linked_app_store_id == package_name:
                    app_id = app.app_id
                    break

        if not app_id:
            logger.warning(
                "No matching AdMob app found for package name", package_name=package_name
            )
            return None

        summary = admob_client.get_earnings_summary(app_id=app_id)
        return {
            "ad_revenue_today": summary.today,
            "ad_revenue_yesterday": summary.yesterday,
            "ad_revenue_7d": summary.last_7_days,
            "ad_revenue_30d": summary.last_30_days,
            "ad_impressions_today": summary.impressions_today,
            "ad_clicks_today": summary.clicks_today,
            "ad_ecpm": summary.ecpm_today,
        }
    except Exception as e:
        logger.warning("Failed to fetch AdMob earnings summary", error=str(e))
        return None


def _fetch_ga4_revenue(
    analytics: AnalyticsClient, start_date: str, end_date: str
) -> dict[str, float] | None:
    """Fetch GA4 revenue report with corrected metrics."""
    try:
        revenue = analytics.get_revenue_report(start_date=start_date, end_date=end_date)
        return {
            "total_revenue": revenue.total_revenue,
            "purchase_revenue": revenue.purchase_revenue,
            "ad_revenue": revenue.ad_revenue,
        }
    except Exception as e:
        logger.warning("Failed to fetch GA4 revenue", error=str(e))
        return None


def _fetch_revenuecat_metrics(
    revenuecat: RevenueCatClient | None, store: str | None = None
) -> dict[str, Any] | None:
    """Fetch RevenueCat revenue metrics. Returns None if all zeros or unavailable.

    When store is set ("app_store" or "play_store"), uses the /charts/revenue
    endpoint which supports store-level filtering. Falls back to overview for
    other metrics (active subs, churn, etc.).
    """
    if not revenuecat:
        return None
    try:
        if store:
            # Use charts endpoint for store-filtered revenue
            store_rev = revenuecat.get_revenue_by_store(store=store)
            if store_rev["revenue"] == 0 and store_rev["mrr"] == 0:
                return None
            return {
                "active_subscriptions": None,
                "mrr": store_rev["mrr"],
                "revenue": store_rev["revenue"],
                "active_trials": None,
                "new_subscribers": None,
                "churn_rate": None,
                "store": store,
            }

        rc_overview = revenuecat.get_overview_metrics(store=store)
        # If everything is zero, RevenueCat isn't actively used for this app
        if (
            rc_overview.active_subscribers == 0
            and rc_overview.mrr == 0.0
            and rc_overview.revenue == 0.0
        ):
            logger.info("RevenueCat returned all zeros — app may not use subscriptions")
            return None
        return {
            "active_subscriptions": rc_overview.active_subscribers,
            "mrr": rc_overview.mrr,
            "revenue": rc_overview.revenue,
            "active_trials": rc_overview.active_trials,
            "new_subscribers": rc_overview.new_subscribers,
            "churn_rate": rc_overview.churn_rate,
        }
    except Exception as e:
        logger.warning("Failed to fetch RevenueCat metrics", error=str(e))
        return None


def _build_funnel_events(
    event_counts: dict[str, int],
    _installs: int,
    d1_active: int,
    _admob_metrics: dict[str, Any] | None,
    rc_metrics: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Build the events dict expected by the analyzer.

    For ad-monetized apps (no subscription events), we map:
    - onboarding_complete = core_feature_users (e.g., emi_calculator_calculate_clicked)
    - paywall_view = ad_impression users (users who saw ads)
    - trial_start = ad_click users (users who engaged with ads)
    - paid_conversion = users who generated measurable revenue

    For subscription apps, we use the real events directly.
    """
    # Check if app has active subscription flow events
    has_sub_events = (
        event_counts.get("paywall_view", 0) > 10
        or event_counts.get("trial_start", 0) > 10
        or event_counts.get("subscription_start", 0) > 10
    )

    if has_sub_events:
        # Subscription-based app — use real events
        return {
            "events": {
                "tutorial_complete": event_counts.get(
                    "tutorial_complete", event_counts.get("onboarding_complete", d1_active)
                ),
                "paywall_view": event_counts.get("paywall_view", 0),
                "trial_start": event_counts.get("trial_start", 0),
                "subscription_start": event_counts.get(
                    "subscription_start", event_counts.get("purchase", 0)
                ),
            }
        }

    # Ad-monetized app — map real engagement events to funnel steps
    # IMPORTANT: event user counts span ALL active users (1M+), but the funnel
    # starts from new installs (~35K). We need to compute engagement RATES from
    # the full population, then apply them to d1_active users for a coherent funnel.
    total_active_users = event_counts.get("session_start", 1)

    core_feature_users_total = (
        event_counts.get("emi_calculator_calculate_clicked", 0)
        or event_counts.get("core_action_completed", 0)
        or event_counts.get("dashboard_viewed", 0)
    )
    ad_impression_users_total = event_counts.get("ad_impression", 0)
    ad_click_users_total = event_counts.get("ad_click", 0)

    # Compute engagement rates from total population
    core_rate = (
        min(1.0, core_feature_users_total / total_active_users) if total_active_users > 0 else 0.7
    )
    ad_view_rate = (
        min(1.0, ad_impression_users_total / total_active_users) if total_active_users > 0 else 0.5
    )
    ad_click_rate = (
        min(1.0, ad_click_users_total / ad_impression_users_total)
        if ad_impression_users_total > 0
        else 0.3
    )
    # Revenue conversion rate: % of ad clickers that generate meaningful revenue
    # Use GA4 ad_impression_revenue users vs ad_click users as a proxy
    revenue_users_total = event_counts.get("ad_impression_revenue", 0)
    revenue_rate = (
        min(1.0, revenue_users_total / ad_click_users_total) if ad_click_users_total > 0 else 0.5
    )

    # Apply rates to d1_active (new install cohort) for consistent funnel
    onboarding = int(d1_active * core_rate)
    paywall = int(onboarding * ad_view_rate)
    trial = int(paywall * ad_click_rate)
    paid = int(trial * min(0.8, revenue_rate))  # Cap at 80% — not all clickers generate revenue

    # If we have RevenueCat data with actual subscribers, use those
    if rc_metrics and rc_metrics.get("active_subscriptions", 0) > 0:
        rc_active = rc_metrics["active_subscriptions"]
        paid = int(trial * 0.8) if rc_active >= trial else rc_active

    return {
        "events": {
            "tutorial_complete": onboarding,
            "paywall_view": paywall,
            "trial_start": trial,
            "subscription_start": paid,
        }
    }


def _build_active_users_dict(
    ga4_active: Any, installs: int, d1_retention_rate: float
) -> dict[str, Any]:
    """Convert ActiveUsersReport model to dictionary."""
    active_dict = ga4_active.model_dump() if hasattr(ga4_active, "model_dump") else dict(ga4_active)
    active_dict["active_users_d1"] = int(installs * d1_retention_rate)
    return active_dict


def _build_retention_dict(
    ga4_retention: Any,
    installs: int,
    d1_ret: float,
    d7_ret: float,
    d30_ret: float,
) -> dict[str, Any]:
    """Convert RetentionReport model to dictionary."""
    ret_dict = (
        ga4_retention.model_dump() if hasattr(ga4_retention, "model_dump") else dict(ga4_retention)
    )
    ret_dict["d1_retention_rate"] = d1_ret
    ret_dict["d7_retention_rate"] = d7_ret
    ret_dict["d30_retention_rate"] = d30_ret
    ret_dict["d7_retention_count"] = int(installs * d7_ret)
    ret_dict["d30_retention_count"] = int(installs * d30_ret)

    cohorts = []
    for c in ret_dict.get("cohorts", []):
        cohorts.append(
            {
                "period": c.get("date", "Unknown"),
                "d1_retention": d1_ret,
                "d7_retention": d7_ret,
                "d30_retention": d30_ret,
                "new_users": c.get("new_users", 0),
                "source": "all",
            }
        )
    ret_dict["cohorts"] = cohorts
    return ret_dict


def _get_latest_db_date(package_name: str) -> str | None:
    """Get the latest date available in the database for the given package."""
    import sqlite3

    from app_manager.storefront_analyst import DEFAULT_DB_PATH

    try:
        conn = sqlite3.connect(str(DEFAULT_DB_PATH))
        cursor = conn.cursor()
        cursor.execute(
            "SELECT MAX(date) FROM listing_performance_by_country WHERE package_name = ?;",
            (package_name,),
        )
        row = cursor.fetchone()
        conn.close()
        return row[0] if row and row[0] else None
    except Exception:
        return None


@mcp.tool()
def run_funnel_analysis(
    package_name: str,
    app_category: str = "utilities",
    date_range: str = "30d",
    ltv_override: float | None = None,
) -> str:
    """Run a full 10-step master funnel analysis with leak detection.

    Integrates data from GA4 Analytics, Play Store, AdMob, and RevenueCat.

    Args:
        package_name: Android app package name (e.g., com.example.app).
        app_category: Industry category for benchmarking (e.g., finance, games, utilities).
        date_range: Time period (e.g., 30d, 7d).
        ltv_override: Optional LTV value. If omitted, uses category average.
    """
    logger.info("Running funnel analysis", package_name=package_name, category=app_category)

    from app_manager.credential_store import get_app_credentials

    creds = get_app_credentials(package_name)

    if creds.has_analytics():
        analytics = AnalyticsClient(
            property_id=creds.ga4_property_id, credentials_path=creds.google_credentials_path
        )
    elif _demo_mode():
        analytics = _get_analytics_client()
    else:
        return _unavailable_funnel(package_name, date_range, ["analytics"])

    store = (
        PlayStoreClient(credentials_path=creds.google_credentials_path)
        if creds.has_play_store()
        else None
    )

    revenuecat = None
    if creds.has_revenuecat():
        try:
            revenuecat = RevenueCatClient(
                api_key=creds.revenuecat_api_key, project_id=creds.revenuecat_project_id
            )
        except Exception as e:
            logger.warning("Failed to init RevenueCat client for funnel analysis", error=str(e))

    admob = None
    if creds.has_admob():
        try:
            from admob_mcp.client import AdMobClient

            admob = AdMobClient(
                account_id=creds.admob_account_id, credentials_path=creds.google_credentials_path
            )
        except Exception as e:
            logger.warning("Failed to init AdMob client for funnel analysis", error=str(e))

    # Determine the best date range to query GA4 to align with Play Store DB
    db_latest = _get_latest_db_date(package_name)
    if db_latest:
        from datetime import datetime, timedelta

        try:
            end_dt = datetime.strptime(db_latest, "%Y-%m-%d")
            days = 30
            if date_range.endswith("d"):
                with suppress(ValueError):
                    days = int(date_range[:-1])
            start_dt = end_dt - timedelta(days=days)
            start_date = start_dt.strftime("%Y-%m-%d")
            end_date = db_latest
            logger.info(
                "Aligning GA4 date range with storefront DB",
                start_date=start_date,
                end_date=end_date,
            )
        except Exception:
            start_date, end_date = _parse_date_range(date_range)
    else:
        start_date, end_date = _parse_date_range(date_range)

    # ─── Fetch data from all sources ─────────────────────────────────────
    # Filter GA4 data to only include Google Play installations to match storefront downloads.
    # This only makes sense for Play Store apps -- Apple doesn't attribute installs as
    # "google-play", so filtering on it for an App Store app silently zeroes out every
    # real GA4 event. Fetch unfiltered for App Store apps instead of guessing Apple's
    # equivalent source string.
    traffic_filter = (
        None if creds.rc_platform == "app_store" else {"firstUserSource": "google-play"}
    )
    try:
        ga4_active = analytics.get_active_users(
            start_date=start_date, end_date=end_date, dimension_filter=traffic_filter
        )
        ga4_retention = analytics.get_retention(
            start_date=start_date, end_date=end_date, dimension_filter=traffic_filter
        )
        ga4_events = analytics.get_events(
            start_date=start_date, end_date=end_date, dimension_filter=traffic_filter
        )
    except Exception as exc:
        logger.warning(
            "Required analytics collection failed",
            package_name=package_name,
            error_type=type(exc).__name__,
        )
        return _unavailable_funnel(package_name, date_range, ["analytics"])
    # Revenue sources
    rc_metrics = _fetch_revenuecat_metrics(revenuecat, store=creds.rc_platform)
    admob_metrics = _fetch_admob_metrics(admob, package_name)
    ga4_revenue = _fetch_ga4_revenue(analytics, start_date, end_date)

    # GCS Play Console fallback if RevenueCat is not present or returns no data
    gcs_revenue = None
    if not rc_metrics and creds.gcs_play_console_bucket and creds.google_credentials_path:
        try:
            from app_manager.gcs_revenue_fetcher import fetch_play_console_revenue

            days_num = 30
            if date_range.endswith("d"):
                with suppress(ValueError):
                    days_num = int(date_range[:-1])
            gcs_revenue = fetch_play_console_revenue(
                credentials_path=creds.google_credentials_path,
                bucket_name=creds.gcs_play_console_bucket,
                package_name=package_name,
                days=days_num,
            )
        except Exception as exc:
            logger.warning("Failed to fetch GCS revenue", error=str(exc))

    try:
        if store is None:
            raise RuntimeError("Play Store listing source is not configured")
        store_details: AppDetails | dict[str, str] = store.get_app_details(
            package_name=package_name
        )
    except Exception as e:
        logger.warning(
            "Play Store listing unavailable for funnel analysis",
            package_name=package_name,
            error_type=type(e).__name__,
        )
        if _demo_mode():
            from play_store_mcp.models import AppDetails

            store_details = AppDetails(
                package_name=package_name,
                title=package_name.split(".")[-1].replace("_", " ").title(),
                short_description="Demo listing description.",
                full_description="Demo listing description for explicit demo mode.",
                default_language="en-US",
            )
        else:
            store_details = {"package_name": package_name}

    logger.info(
        "Data fetched successfully",
        admob_30d=admob_metrics.get("ad_revenue_30d") if admob_metrics else "N/A",
        ga4_revenue=ga4_revenue.get("total_revenue") if ga4_revenue else "N/A",
        rc_metrics="active" if rc_metrics else "inactive",
    )

    # ─── Compute derived metrics ─────────────────────────────────────────
    event_counts = _get_ga4_event_counts(ga4_events)
    installs = _get_installs(ga4_events, ga4_active)
    d1_ret, d7_ret, d30_ret = _calculate_real_retention(ga4_retention)

    # ─── Build analyzer inputs ───────────────────────────────────────────
    days = 30
    if date_range.endswith("d"):
        with suppress(ValueError):
            days = int(date_range[:-1])

    # If RevenueCat is missing but GCS IAP is present, synthesize rc_metrics for the analyzer
    if not rc_metrics and gcs_revenue:
        rc_metrics = {
            "active_subscriptions": gcs_revenue.get("charge_count", 0),
            "mrr": 0.0,
            "revenue": gcs_revenue.get("iap_revenue_30d", 0.0),
            "source": "play_console_gcs",
            "estimated_ltv": round(gcs_revenue.get("iap_revenue_30d", 0.0) / installs * 3, 2)
            if installs > 0
            else 0.0,
        }

    play_store_dict = _prepare_play_store_details(
        store_details, installs, app_category, package_name, days
    )
    if not play_store_dict.get("store_visitors") or not play_store_dict.get("installs"):
        return _unavailable_funnel(
            package_name,
            date_range,
            ["storefront"],
            status="partial",
        )
    # Standardize on Play Store storefront installs as the unified baseline denominator for the cohort funnel
    install_cohort = play_store_dict["installs"]
    d1_active = int(install_cohort * d1_ret)
    active_dict = _build_active_users_dict(ga4_active, install_cohort, d1_ret)
    events_dict = _build_funnel_events(
        event_counts, install_cohort, d1_active, admob_metrics, rc_metrics
    )
    retention_dict = _build_retention_dict(ga4_retention, install_cohort, d1_ret, d7_ret, d30_ret)

    # Compute a real 3-month LTV estimate from all revenue sources
    if ltv_override is None:
        ad_rev_30d = (admob_metrics or {}).get("ad_revenue_30d", 0.0)
        # Include subscription net revenue from RevenueCat or GCS Play Console (which was synthesized into rc_metrics)
        sub_rev_30d = (rc_metrics or {}).get("revenue", 0.0) if rc_metrics else 0.0
        total_rev_30d = ad_rev_30d + sub_rev_30d
        if total_rev_30d > 0 and installs > 0:
            # Per-install monthly blended revenue * 3 months (conservative retention assumption)
            ltv_per_install = total_rev_30d / installs
            ltv_override = round(ltv_per_install * 3, 2)
            logger.info(
                "Using blended LTV (AdMob + subscriptions)",
                ltv=ltv_override,
                ad_revenue_30d=ad_rev_30d,
                sub_revenue_30d=sub_rev_30d,
                total_rev_30d=total_rev_30d,
            )

    # ─── Run analysis ────────────────────────────────────────────────────
    analysis = analyzer.analyze_funnel(
        ga4_active_users=active_dict,
        ga4_retention=retention_dict,
        ga4_events=events_dict,
        play_store_details=play_store_dict,
        revenuecat_metrics=rc_metrics,
        app_id=package_name,
        app_category=app_category,
        ltv_override=ltv_override,
        analysis_date=f"{start_date} to {end_date}",
    )

    # ─── Enrich output with real revenue data ────────────────────────────
    output = json.loads(analysis.model_dump_json(indent=2))
    output["revenue_data"] = {
        "admob": admob_metrics,
        "ga4_revenue": ga4_revenue,
        "revenuecat": rc_metrics
        if rc_metrics and rc_metrics.get("source") != "play_console_gcs"
        else None,
        "gcs_iap": gcs_revenue,
    }
    output["play_store_details"] = play_store_dict
    output["real_event_mapping"] = {
        "note": "Events were mapped from real GA4 data",
        "core_feature_users": event_counts.get("emi_calculator_calculate_clicked", 0)
        or event_counts.get("dashboard_viewed", 0),
        "ad_impression_users": event_counts.get("ad_impression", 0),
        "ad_click_users": event_counts.get("ad_click", 0),
        "session_start_users": event_counts.get("session_start", 0),
        "first_open_users": event_counts.get("first_open", 0),
        "total_30d_users": ga4_active.total_users if hasattr(ga4_active, "total_users") else 0,
        "average_dau": ga4_active.average_dau if hasattr(ga4_active, "average_dau") else 0,
    }
    output["raw_event_counts"] = event_counts
    captured_at = datetime.now(UTC).isoformat()
    output["status"] = "success"
    output["period"] = date_range
    output["provenance"] = {
        "source": "funnel_engine",
        "captured_at": captured_at,
        "period": date_range,
        "is_live": True,
    }
    output["estimated_vs_observed"] = {
        "store_impressions": "estimated",
        "store_visitors": "observed",
        "installs": "observed",
        "retention": "estimated_from_observed_cohorts",
        "events": "observed_and_mapped",
    }
    output["ranked_leaks"] = [
        {
            "rank": rank,
            "stage": leak.get("name"),
            "score": leak.get("monthly_revenue_impact"),
            "conversion_rate": leak.get("conversion_rate"),
            "benchmark_rate": leak.get("benchmark_rate"),
            "gap": leak.get("gap"),
            "estimated_monthly_impact": leak.get("monthly_revenue_impact"),
            "estimated": True,
            "observed": bool(leak.get("has_data")),
            "provenance": output["provenance"],
        }
        for rank, leak in enumerate(output.get("leaks", []), 1)
    ]

    return json.dumps(output, indent=2)


@mcp.tool()
def get_funnel_health_score(
    package_name: str,
    app_category: str = "utilities",
    date_range: str = "30d",
) -> str:
    """Get just the quick health score (0-100) and top leak for the app.

    Args:
        package_name: Android app package name.
        app_category: Industry category.
        date_range: Time period.
    """
    # This is a lightweight wrapper around full analysis that only returns the score and top leak
    full_json = run_funnel_analysis(package_name, app_category, date_range)
    data = json.loads(full_json)

    top_leak = data.get("leaks", [None])[0]

    result = {
        "score": data.get("funnel_health_score"),
        "top_leak": top_leak,
        "total_monthly_revenue_impact": data.get("total_monthly_revenue_impact"),
        "summary": data.get("summary"),
        "revenue_data": data.get("revenue_data"),
    }

    return json.dumps(result, indent=2)


@mcp.tool()
def get_retention_analysis(
    package_name: str,
    app_category: str = "utilities",
    date_range: str = "30d",
) -> str:
    """Analyze retention curves (D1, D7, D30) vs category benchmarks.

    Args:
        package_name: Android app package name.
        app_category: Industry category.
        date_range: Time period.
    """
    logger.info("Running retention analysis", package_name=package_name, category=app_category)

    from app_manager.credential_store import get_app_credentials

    creds = get_app_credentials(package_name)

    if creds.ga4_property_id:
        analytics = AnalyticsClient(
            property_id=creds.ga4_property_id, credentials_path=creds.google_credentials_path
        )
    else:
        analytics = _get_analytics_client()

    start_date, end_date = _parse_date_range(date_range)
    ga4_retention = analytics.get_retention(start_date=start_date, end_date=end_date)
    ga4_acquisition = analytics.get_user_acquisition(start_date=start_date, end_date=end_date)
    ga4_events = analytics.get_events(start_date=start_date, end_date=end_date)

    installs = _get_installs(ga4_events, None)
    d1_ret, d7_ret, d30_ret = _calculate_real_retention(ga4_retention)

    ga4_retention_dict = _build_retention_dict(ga4_retention, installs, d1_ret, d7_ret, d30_ret)

    acq_dict = (
        ga4_acquisition.model_dump()
        if hasattr(ga4_acquisition, "model_dump")
        else dict(ga4_acquisition)
    )
    acq_dict["retention_by_source"] = [
        {
            "source": ch.get("channel", "unknown"),
            "d1_retention": d1_ret,
            "d7_retention": d7_ret,
            "new_users": ch.get("new_users", 0),
        }
        for ch in acq_dict.get("channels", [])
    ]

    analysis = analyzer.analyze_retention(
        ga4_retention=ga4_retention_dict,
        ga4_acquisition=acq_dict,
        app_id=package_name,
        app_category=app_category,
    )

    return analysis.model_dump_json(indent=2)


@mcp.tool()
def get_benchmark_comparison(
    package_name: str,
    app_category: str = "utilities",
    date_range: str = "30d",
) -> str:
    """Compare all app metrics to category benchmarks.

    Args:
        package_name: Android app package name.
        app_category: Industry category.
        date_range: Time period.
    """
    logger.info("Running benchmark comparison", package_name=package_name, category=app_category)

    from app_manager.credential_store import get_app_credentials

    creds = get_app_credentials(package_name)

    if creds.ga4_property_id:
        analytics = AnalyticsClient(
            property_id=creds.ga4_property_id, credentials_path=creds.google_credentials_path
        )
    else:
        analytics = _get_analytics_client()

    store = _get_play_store_client()

    revenuecat = None
    if creds.has_revenuecat():
        try:
            revenuecat = RevenueCatClient(
                api_key=creds.revenuecat_api_key, project_id=creds.revenuecat_project_id
            )
        except Exception as e:
            logger.warning("Failed to init RevenueCat client for benchmarks", error=str(e))

    start_date, end_date = _parse_date_range(date_range)
    ga4_retention = analytics.get_retention(start_date=start_date, end_date=end_date)
    ga4_events = analytics.get_events(start_date=start_date, end_date=end_date)
    store_details = store.get_app_details(package_name=package_name)

    rc_metrics = _fetch_revenuecat_metrics(revenuecat, store=creds.rc_platform)

    installs = _get_installs(ga4_events, None)
    d1_ret, d7_ret, d30_ret = _calculate_real_retention(ga4_retention)

    days = 30
    if date_range.endswith("d"):
        with suppress(ValueError):
            days = int(date_range[:-1])

    # GCS Play Console fallback if RevenueCat is not present or returns no data
    gcs_revenue = None
    if not rc_metrics and creds.gcs_play_console_bucket and creds.google_credentials_path:
        try:
            from app_manager.gcs_revenue_fetcher import fetch_play_console_revenue

            gcs_revenue = fetch_play_console_revenue(
                credentials_path=creds.google_credentials_path,
                bucket_name=creds.gcs_play_console_bucket,
                package_name=package_name,
                days=days,
            )
        except Exception as exc:
            logger.warning("Failed to fetch GCS revenue for benchmarks", error=str(exc))

    if not rc_metrics and gcs_revenue:
        rc_metrics = {
            "active_subscriptions": gcs_revenue.get("charge_count", 0),
            "mrr": 0.0,
            "revenue": gcs_revenue.get("iap_revenue_30d", 0.0),
            "source": "play_console_gcs",
            "estimated_ltv": round(gcs_revenue.get("iap_revenue_30d", 0.0) / installs * 3, 2)
            if installs > 0
            else 0.0,
        }

    ga4_retention_dict = _build_retention_dict(ga4_retention, installs, d1_ret, d7_ret, d30_ret)
    store_details_dict = _prepare_play_store_details(
        store_details, installs, app_category, package_name, days
    )

    analysis = analyzer.compare_benchmarks(
        ga4_data=ga4_retention_dict,
        revenuecat_data=rc_metrics,
        play_store_data=store_details_dict,
        app_id=package_name,
        app_category=app_category,
    )

    return analysis.model_dump_json(indent=2)


@mcp.tool()
async def ingest_play_store_reports(
    package_name: str,
    backfill: bool = False,
) -> str:
    """Ingest storefront performance reports from GCS into the local database and export to JSON.

    Args:
        package_name: Android app package name (e.g. com.finance.loan.emicalculator).
        backfill: If True, backfill all historical GCS files. If False, only ingest the current and previous month's reports.
    """
    from app_manager.storefront_analyst import backfill_history, ingest_latest_month

    logger.info("Ingesting Play Store reports", package_name=package_name, backfill=backfill)
    try:
        if backfill:
            result = await backfill_history(package_name)
        else:
            result = await ingest_latest_month(package_name)
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.exception("Failed to ingest storefront reports", error=str(e))
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool()
def ingest_app_store_reports(package_name: str) -> str:
    """Ingest App Store Connect analytics (impressions, product page views, downloads)
    into the local database via the asc CLI.

    Args:
        package_name: iOS bundle ID (e.g. com.pomodoro.krypt.timemanagement.focus.app).
    """
    from app_manager.asc_analytics_ingest import ingest_asc_reports

    logger.info("Ingesting App Store Connect analytics reports", package_name=package_name)
    try:
        result = ingest_asc_reports(package_name)
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.exception("Failed to ingest App Store Connect analytics reports", error=str(e))
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool()
def get_historical_listing_conversion(
    package_name: str,
    metric_type: str,
) -> str:
    """Retrieve historical store listing conversion rate metrics from SQLite.

    Args:
        package_name: Android app package name (e.g. com.finance.loan.emicalculator).
        metric_type: The type of metrics to query. Must be one of 'country', 'traffic_source', or 'search_term'.
    """
    from app_manager.storefront_analyst import DEFAULT_DB_PATH
    from funnel_engine.db import (
        get_country_performance,
        get_search_performance,
        get_traffic_performance,
    )

    logger.info(
        "Querying historical storefront metrics", package_name=package_name, metric_type=metric_type
    )
    try:
        if metric_type == "country":
            data = get_country_performance(DEFAULT_DB_PATH, package_name)
        elif metric_type == "traffic_source":
            data = get_traffic_performance(DEFAULT_DB_PATH, package_name)
        elif metric_type == "search_term":
            data = get_search_performance(DEFAULT_DB_PATH, package_name)
        else:
            return json.dumps(
                {
                    "success": False,
                    "error": f"Invalid metric_type '{metric_type}'. Must be one of: country, traffic_source, search_term.",
                },
                indent=2,
            )

        return json.dumps(
            {
                "success": True,
                "package_name": package_name,
                "metric_type": metric_type,
                "records": data,
            },
            indent=2,
        )
    except Exception as e:
        logger.exception("Failed to query historical storefront metrics", error=str(e))
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool()
def generate_app_rulebook(
    package_name: str,
    force: bool = False,
) -> str:
    """Generate a conservative starting rulebooks/<package_name>.yaml for a new app.

    Onboarding a new app to the autonomous experiment system previously required
    hand-writing a rulebook YAML. This pulls live listing data (title/description
    length, current keywords) and monetization signals (RevenueCat/AdMob credential
    presence) to seed metadata constraints, ASO keywords, and monetization flags.
    Safety rules always default to requiring Telegram approval on every mutating
    action -- review the generated file and loosen it by hand only after the app's
    write path has been exercised and verified at least once.

    Args:
        package_name: App package name (Android) or bundle ID (iOS). Must already
            have an entry in config/apps.json (or fall back to global .env).
        force: Overwrite an existing rulebook file if one already exists.

    Returns:
        A status message naming the rulebook path, or an error if generation failed.
    """
    import yaml

    from app_manager.credential_store import get_app_credentials

    creds = get_app_credentials(package_name)
    rulebook_path = Path("rulebooks") / f"{package_name}.yaml"
    if rulebook_path.exists() and not force:
        return f"Rulebook already exists at {rulebook_path} -- pass force=True to overwrite."

    is_ios = creds.has_app_store_connect() and not creds.has_play_store()
    title: str | None = None
    target_keywords: list[str] = []

    if creds.has_play_store():
        try:
            store = PlayStoreClient(credentials_path=creds.google_credentials_path)
            title = store.get_listing(package_name).title
        except Exception as e:
            logger.warning("generate_app_rulebook: Play Store listing fetch failed", error=str(e))

        try:
            from aso_keyword_mcp.client import ASOClient

            keywords = ASOClient().get_app_keywords(package_name)
            target_keywords = list(
                dict.fromkeys([*keywords.title_keywords, *keywords.description_keywords])
            )[:15]
        except Exception as e:
            logger.warning("generate_app_rulebook: keyword extraction failed", error=str(e))
    else:
        try:
            from app_store_mcp.client import AppStoreClient

            details = AppStoreClient().get_app_details(package_name)
            title = details.get("title")
        except Exception as e:
            logger.warning("generate_app_rulebook: App Store lookup failed", error=str(e))

    if is_ios:
        metadata_constraints: dict[str, Any] = {
            "title": {"max_length": 30},
            "subtitle": {"max_length": 30},
            "full_description": {"max_length": 4000},
        }
        interceptor_tools = ["app_store_connect/update_listing"]
    else:
        metadata_constraints = {
            "title": {
                "max_length": 30,
                "required_keywords": [title.split()[0]] if title else [],
            },
            "short_description": {"max_length": 80},
            "full_description": {"max_length": 4000},
        }
        interceptor_tools = ["play_store/update_listing"]

    has_subscriptions = creds.has_revenuecat()
    revenue_gate_type = "none"
    if has_subscriptions:
        try:
            rc = RevenueCatClient(
                api_key=creds.revenuecat_api_key, project_id=creds.revenuecat_project_id
            )
            offerings = rc.list_offerings()
            revenue_gate_type = "subscription" if offerings else "none"
        except Exception as e:
            logger.warning("generate_app_rulebook: RevenueCat lookup failed", error=str(e))

    rulebook = {
        "package_name": package_name,
        "last_updated": datetime.now(UTC).date().isoformat(),
        "metadata_constraints": metadata_constraints,
        "monetization": {
            "status": "organic_experiment",
            "has_ads": creds.has_admob(),
            "has_subscriptions": has_subscriptions,
            "allowed_ad_budget_monthly": 0.0,
            "revenue_gate_type": revenue_gate_type,
        },
        "safety_rules": {
            "require_telegram_approval": True,
            "interceptor_tools": interceptor_tools,
            "telegram_timeout_seconds": 300,
        },
        "aso_strategy": {
            "target_keywords": target_keywords,
            "preferred_tone": "clear, benefit-led, trustworthy",
        },
    }

    rulebook_path.parent.mkdir(parents=True, exist_ok=True)
    with rulebook_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(rulebook, f, sort_keys=False, allow_unicode=True)

    logger.info("Generated app rulebook", package_name=package_name, path=str(rulebook_path))
    return (
        f"Generated rulebook at {rulebook_path}. Review it -- especially "
        "metadata_constraints and target_keywords -- before enabling any "
        "auto_low_risk experiment execution mode for this app."
    )
