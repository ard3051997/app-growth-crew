import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, cast

import structlog
from fastapi import APIRouter, HTTPException

from funnel_engine.db import DEFAULT_DB_PATH, get_all_latest_snapshots, get_db_experiments

router = APIRouter()
logger = structlog.get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def get_apps_config() -> list[dict[str, Any]]:
    apps_file = PROJECT_ROOT / "config" / "apps.json"
    if not apps_file.exists():
        # Fallback to empty list or default
        return []
    try:
        with apps_file.open() as f:
            config = cast("dict[str, Any]", json.load(f))
            return cast("list[dict[str, Any]]", config.get("apps", []))
    except Exception as exc:
        logger.warning("Failed to load apps config", path=str(apps_file), error=str(exc))
        return []


def get_latest_system_trust() -> str:
    try:
        conn = sqlite3.connect(str(DEFAULT_DB_PATH))
        cursor = conn.cursor()
        cursor.execute("SELECT current_trust_tier FROM system_confidence ORDER BY id DESC LIMIT 1;")
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else "moderate"
    except Exception:
        return "moderate"


def _revenue_provenance(
    snapshot: dict,
    raw_revenue: dict,
    snapshot_captured_at: str | None,
) -> tuple[dict[str, dict], float | None, float | None]:
    """Return metric-level values and source timestamps from a cached snapshot."""
    try:
        source_details = json.loads(snapshot.get("source_status_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        source_details = {}
    if not isinstance(source_details, dict):
        source_details = {}

    raw_revenuecat = raw_revenue.get("revenuecat")
    revenuecat = (
        cast("dict[str, Any]", raw_revenuecat) if isinstance(raw_revenuecat, dict) else None
    )
    raw_gcs_iap = raw_revenue.get("gcs_iap")
    gcs_iap = cast("dict[str, Any]", raw_gcs_iap) if isinstance(raw_gcs_iap, dict) else None
    raw_app_store = raw_revenue.get("app_store")
    app_store = cast("dict[str, Any]", raw_app_store) if isinstance(raw_app_store, dict) else None
    raw_metric_values = raw_revenue.get("metric_values")
    metric_values = (
        cast("dict[str, Any]", raw_metric_values) if isinstance(raw_metric_values, dict) else {}
    )

    subscription_value = metric_values.get("subscription_revenue_30d")
    if subscription_value is None and revenuecat is not None:
        subscription_value = revenuecat.get("revenue")
    elif subscription_value is None and app_store is not None:
        subscription_value = app_store.get("subscription_revenue_30d")

    iap_value = metric_values.get("iap_revenue_30d")
    if iap_value is None and gcs_iap is not None:
        iap_value = gcs_iap.get("iap_revenue_30d")
    elif iap_value is None and app_store is not None:
        iap_value = app_store.get("iap_revenue_30d")

    def metric_detail(
        metric: str,
        value: float | None,
        fallback_source: str,
        *legacy_keys: str,
    ) -> dict:
        detail = source_details.get(metric)
        if not isinstance(detail, dict):
            detail = next(
                (
                    source_details[key]
                    for key in legacy_keys
                    if isinstance(source_details.get(key), dict)
                ),
                {},
            )
        known = value is not None
        carried_forward = bool(detail.get("carried_forward"))
        original_captured_at = detail.get("original_captured_at") or detail.get("captured_at")
        if known and original_captured_at is None and not carried_forward:
            original_captured_at = snapshot_captured_at
        return {
            "value": value,
            "source": detail.get("source") or (fallback_source if known else "unavailable"),
            "status": detail.get("status") or ("success" if known else "unavailable"),
            "captured_at": original_captured_at,
            "original_captured_at": original_captured_at,
            "carried_forward": carried_forward,
            "period": "30d" if metric != "mrr" else "current",
        }

    ad_value = snapshot.get("ad_revenue_30d")
    mrr_value = snapshot.get("mrr")
    provenance = {
        "ad": metric_detail("ad_revenue", ad_value, "admob", "admob"),
        "subscription": metric_detail(
            "subscription_revenue",
            subscription_value,
            "revenuecat" if revenuecat is not None else "app_store",
            "revenuecat",
        ),
        "mrr": metric_detail("mrr", mrr_value, "revenuecat", "revenuecat"),
        "iap": metric_detail(
            "iap_revenue",
            iap_value,
            "gcs_revenue" if gcs_iap is not None else "app_store",
            "gcs_revenue",
            "app_store",
        ),
    }
    return provenance, subscription_value, iap_value


@router.get("/")
def get_portfolio(period: str = "30d") -> dict[str, Any]:
    """Returns all apps from apps.json with latest metrics from app_metrics_snapshots."""
    if period != "30d":
        raise HTTPException(
            status_code=422,
            detail="Portfolio snapshots currently support only a complete 30d revenue period",
        )
    apps = get_apps_config()

    try:
        db_exps = get_db_experiments(DEFAULT_DB_PATH)
    except Exception:
        db_exps = []

    try:
        snapshots = get_all_latest_snapshots(DEFAULT_DB_PATH)
        snapshot_map = {s["package_name"]: s for s in snapshots}
    except Exception:
        snapshot_map = {}

    portfolio_apps: list[dict[str, Any]] = []
    opportunities: list[dict[str, Any]] = []
    for app in apps:
        package_name = app.get("package_name")
        display_name = app.get("display_name", app.get("name", package_name))

        active_exps = len(
            [
                e
                for e in db_exps
                if e["app_package"] == package_name and e["status"] in ("active", "measuring")
            ]
        )

        snap = snapshot_map.get(package_name, {})
        captured_at = snap.get("data_as_of") or snap.get("created_at")

        # Extract revenue values — prefer period-specific field when available
        raw_rev: dict = {}
        try:
            raw_rev = json.loads(snap.get("raw_revenue_json") or "{}")
        except Exception as exc:
            logger.debug("Malformed cached revenue snapshot", app=package_name, error=str(exc))
        revenue_provenance, subscription_revenue_30d, iap_revenue_30d = _revenue_provenance(
            snap, raw_rev, captured_at
        )

        # Period-aware AdMob revenue: 7d uses ad_revenue_7d from admob block if present
        if period == "7d":
            ad_rev = raw_rev.get("admob", {}).get("ad_revenue_7d") or 0.0
            rc_rev = 0.0
        else:
            ad_rev = snap.get("ad_revenue_30d", 0) or 0.0
            rc_rev = snap.get("rc_revenue_30d", 0) or 0.0

        # Check if there is exact profit in GCS fallback
        gcs_profit = None
        if isinstance(raw_rev.get("gcs_iap"), dict):
            gcs_profit = raw_rev["gcs_iap"].get("iap_profit_30d")

        # Check if there is exact profit in App Store Connect fallback
        asc_profit = None
        if isinstance(raw_rev.get("app_store"), dict):
            asc_profit = raw_rev["app_store"].get("iap_profit_30d")

        if gcs_profit is not None:
            profit_30d = ad_rev + gcs_profit
        elif asc_profit is not None:
            profit_30d = ad_rev + asc_profit
        else:
            profit_30d = ad_rev + (rc_rev * 0.85)

        # Extract cached Google Ads spend from raw_revenue_json if previously stored
        google_ads_spend_30d = None
        if isinstance(raw_rev.get("google_ads"), dict):
            google_ads_spend_30d = raw_rev["google_ads"].get("cost_usd")

        # Safely parse installs_7d JSON
        installs_7d = []
        if snap.get("installs_7d"):
            try:
                installs_7d = json.loads(snap["installs_7d"])
            except Exception as exc:
                logger.debug("Malformed cached install history", app=package_name, error=str(exc))

        # Build worst_stage object if leak data exists
        worst_stage = None
        if snap.get("top_leak_name") and snap["top_leak_name"] != "N/A":
            worst_stage = {
                "name": snap["top_leak_name"],
                "value": snap.get("top_leak_value", 0),
                "benchmark": snap.get("top_leak_benchmark", 0),
            }

        app_opportunities: list[dict[str, Any]] = []
        raw_funnel: dict = {}
        try:
            raw_funnel = json.loads(snap.get("raw_funnel_json") or "{}")
        except Exception as exc:
            logger.debug("Malformed cached funnel snapshot", app=package_name, error=str(exc))
        for leak_index, leak in enumerate(raw_funnel.get("leaks") or []):
            if not isinstance(leak, dict) or not leak.get("has_data", False):
                continue
            opportunity = {
                "id": f"{package_name}:funnel:{leak_index}:{leak.get('name', 'unknown')}",
                "app_package": package_name,
                "title": f"Improve {leak.get('name', 'funnel stage')}",
                "summary": leak.get("insight"),
                "impact": leak.get("monthly_revenue_impact"),
                "impact_unit": "estimated_monthly_revenue",
                "freshness": captured_at,
                "estimated": True,
                "observed": True,
                "provenance": {
                    "source": "app_metrics_snapshots/funnel_engine",
                    "captured_at": captured_at,
                    "period": period,
                    "is_live": False,
                },
            }
            app_opportunities.append(opportunity)
            opportunities.append(opportunity)
        app_opportunities.sort(key=lambda item: item.get("impact") or 0, reverse=True)

        portfolio_apps.append(
            {
                "package_name": package_name,
                "display_name": display_name,
                "funnel_health_score": snap.get("funnel_health_score"),
                "mrr": snap.get("mrr", 0),
                "mrr_change_pct": snap.get("mrr_change_pct", 0),
                "revenue_30d": (
                    ad_rev + rc_rev
                    if period == "7d"
                    else snap.get("total_revenue_30d", 0) or (ad_rev + rc_rev)
                ),
                "profit_30d": profit_30d,
                "revenue_change_pct": snap.get("mrr_change_pct", 0),
                "ad_revenue_30d": ad_rev,
                "subscription_revenue_30d": subscription_revenue_30d,
                "iap_revenue_30d": iap_revenue_30d,
                "revenue_provenance": revenue_provenance,
                "google_ads_spend_30d": google_ads_spend_30d,
                "installs_7d": installs_7d,
                "active_experiments": active_exps,
                "worst_stage": worst_stage,
                "top_opportunity": app_opportunities[0] if app_opportunities else None,
                "as_of": captured_at,
                "freshness": captured_at,
                "source": "app_metrics_snapshots" if snap else "unavailable",
                "partial": bool(snap.get("is_partial")) if snap else True,
                "estimated_vs_observed": raw_funnel.get("estimated_vs_observed", {}),
                "period": period,
            }
        )

    opportunities.sort(key=lambda item: item.get("impact") or 0, reverse=True)
    for rank, opportunity in enumerate(opportunities, 1):
        opportunity["rank"] = rank
    return {
        "apps": portfolio_apps,
        "opportunities": opportunities,
        "top_opportunity": opportunities[0] if opportunities else None,
    }


@router.get("/summary")
def get_portfolio_summary(period: str = "30d") -> dict[str, Any]:
    """Aggregated metrics across all apps based on DB snapshots."""
    if period != "30d":
        raise HTTPException(
            status_code=422,
            detail="Portfolio snapshots currently support only a complete 30d revenue period",
        )
    try:
        db_exps = get_db_experiments(DEFAULT_DB_PATH)
        active_count = len([e for e in db_exps if e["status"] in ("active", "measuring")])
        pending_count = len([e for e in db_exps if e["status"] == "proposed"])
    except Exception:
        active_count = 0
        pending_count = 0

    try:
        snapshots = get_all_latest_snapshots(DEFAULT_DB_PATH)
        total_mrr = sum(s.get("mrr", 0) or 0 for s in snapshots)
        total_revenue = 0.0
        total_profit = 0.0
        total_ad_revenue = 0.0
        for s in snapshots:
            raw_rev: dict = {}
            try:
                raw_rev = json.loads(s.get("raw_revenue_json") or "{}")
            except Exception as exc:
                logger.debug(
                    "Malformed cached portfolio revenue snapshot",
                    app=s.get("package_name"),
                    error=str(exc),
                )
            if period == "7d":
                ad_rev = raw_rev.get("admob", {}).get("ad_revenue_7d") or 0.0
                rc_rev = 0.0
            else:
                ad_rev = s.get("ad_revenue_30d", 0) or 0.0
                rc_rev = s.get("rc_revenue_30d", 0) or 0.0

            # Check for exact profit
            gcs_profit = None
            if isinstance(raw_rev.get("gcs_iap"), dict):
                gcs_profit = raw_rev["gcs_iap"].get("iap_profit_30d")

            asc_profit = None
            if isinstance(raw_rev.get("app_store"), dict):
                asc_profit = raw_rev["app_store"].get("iap_profit_30d")

            if gcs_profit is not None:
                total_profit += ad_rev + gcs_profit
            elif asc_profit is not None:
                total_profit += ad_rev + asc_profit
            else:
                total_profit += ad_rev + (rc_rev * 0.85)

            total_ad_revenue += ad_rev
            total_revenue += (
                ad_rev + rc_rev
                if period == "7d"
                else s.get("total_revenue_30d", 0) or (ad_rev + rc_rev)
            )
    except Exception:
        total_mrr = 0
        total_ad_revenue = 0
        total_revenue = 0.0
        total_profit = 0.0

    trust_tier = get_latest_system_trust()

    return {
        "portfolio_summary": {
            "total_mrr": total_mrr,
            "total_revenue_30d": total_revenue,
            "total_profit_30d": total_profit,
            "total_ad_revenue_30d": total_ad_revenue,
            "active_experiments": active_count,
            "pending_approvals": pending_count,
            "trust_tier": trust_tier,
        }
    }


@router.get("/costs")
def get_portfolio_costs() -> dict[str, dict[str, Any]]:
    """Fetch Google Ads spend (cost_usd) for all apps in parallel.

    Returns a flat dict mapping package_name → cost_usd (float | null).
    Apps without Google Ads config return null.
    """
    from app_manager.credential_store import get_app_credentials
    from app_manager.google_ads_fetcher import fetch_google_ads_metrics

    apps = get_apps_config()
    results: dict[str, Any] = {}

    def _fetch_one(app: dict[str, Any]) -> tuple[str, Any]:
        pkg = app.get("package_name", "")
        try:
            creds = get_app_credentials(pkg)
            config_path = creds.google_ads_config_path
            if not creds.has_google_ads() or not config_path or not creds.google_ads_customer_id:
                return pkg, None
            data = fetch_google_ads_metrics(config_path, creds.google_ads_customer_id, days=30)
            return pkg, data.get("cost_usd") if data else None
        except Exception:
            return pkg, None

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_fetch_one, app): app for app in apps}
        for fut in as_completed(futures, timeout=15):
            try:
                pkg, cost = fut.result()
                results[pkg] = cost
            except Exception:
                pkg = futures[fut].get("package_name", "")
                results[pkg] = None

    return {"costs": results}
