import json
import os
import stat
import zipfile
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any, TypedDict, cast

import structlog
from fastapi import APIRouter, HTTPException, UploadFile
from fastapi import File as FastAPIFile
from pydantic import BaseModel, ValidationError

from analytics_mcp.client import AnalyticsClient
from api_server.auth import config_writes_enabled
from api_server.routes.portfolio import get_apps_config
from app_manager import store_listing_client
from app_manager.config import AppManagerConfig
from app_manager.credential_store import PROJECT_ROOT, _load_apps_config, get_app_credentials
from app_manager.experiment_recommender import (
    ExperimentRecommendationRequest,
    recommend_experiment_designs,
)
from app_manager.store_conversion_proposals import (
    ListingSnapshot,
    ListingText,
    ProposalDataError,
    StoreConversionProposalRequest,
    build_store_conversion_proposal,
    load_rulebook,
    make_listing_snapshot,
    redact_rulebook,
    submit_store_conversion_proposal,
)
from app_manager.storefront_analyst import DEFAULT_DB_PATH
from aso_keyword_mcp.client import ASOClient
from funnel_engine.db import (
    get_country_performance,
    get_db_experiments,
    get_latest_app_snapshot,
    get_search_performance,
    get_source_watermarks,
    get_traffic_performance,
)
from funnel_engine_mcp.server import (
    _fetch_admob_metrics,
    _fetch_ga4_revenue,
    _fetch_revenuecat_metrics,
    _parse_date_range,
    run_funnel_analysis,
)
from journey_map_mcp.server import parse_events_md
from play_store_mcp.client import PlayStoreClient

router = APIRouter()
logger = structlog.get_logger(__name__)

MASKED_VALUE = "********"
MAX_ZIP_BYTES = 10 * 1024 * 1024
MAX_ZIP_MEMBERS = 2_000
MAX_ZIP_MEMBER_BYTES = 5 * 1024 * 1024
MAX_ZIP_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
APP_CONFIG_WRITABLE_KEYS = frozenset(
    {
        "display_name",
        "name",
        "app_category",
        "google_credentials_path",
        "ga4_property_id",
        "revenuecat_api_key",
        "revenuecat_project_id",
        "rc_platform",
        "admob_account_id",
        "gcs_play_console_bucket",
        "google_ads_config_path",
        "google_ads_customer_id",
        "app_store_connect_key_id",
        "app_store_connect_issuer_id",
        "app_store_connect_private_key_path",
        "team_id",
        "jira_url",
        "jira_username",
        "jira_api_token",
        "confluence_url",
        "confluence_username",
        "events_md_path",
    }
)
APP_CONFIG_SENSITIVE_KEYS = frozenset(
    {
        "google_credentials_path",
        "revenuecat_api_key",
        "google_ads_config_path",
        "app_store_connect_private_key_path",
        "jira_api_token",
        "events_md_path",
    }
)


class ReviewAnalysisRow(TypedDict):
    rating: int
    comment: str


class StageCorrelation(TypedDict):
    count: int
    rating_sum: int
    reviews: list[dict[str, Any]]


class KeywordCount(TypedDict):
    keyword: str
    count: int
    sentiment: str


def _demo_mode() -> bool:
    return os.environ.get("MCP_GC_DEMO_MODE") == "1"


def _enrich_funnel_response(
    data: dict[str, Any],
    *,
    source: str,
    captured_at: str | None,
    period: str,
    is_live: bool,
) -> dict[str, Any]:
    """Add additive provenance and ranking fields to the established funnel contract."""
    provenance = {
        "source": source,
        "captured_at": captured_at,
        "period": period,
        "is_live": is_live,
    }
    data.setdefault("status", "success")
    data.setdefault("provenance", provenance)
    raw_leaks = data.get("leaks")
    leaks: list[Any] = raw_leaks if isinstance(raw_leaks, list) else []
    data.setdefault(
        "ranked_leaks",
        [
            {
                "rank": rank,
                "stage": leak.get("name"),
                "score": leak.get("monthly_revenue_impact"),
                "conversion_rate": leak.get("conversion_rate"),
                "benchmark_rate": leak.get("benchmark_rate"),
                "gap": leak.get("gap"),
                "estimated_monthly_impact": leak.get("monthly_revenue_impact"),
                "estimated": leak.get("monthly_revenue_impact") is not None,
                "observed": bool(leak.get("has_data", False)),
                "provenance": provenance,
            }
            for rank, leak in enumerate(leaks, 1)
            if isinstance(leak, dict)
        ],
    )
    return data


def _is_sensitive_app_config(key: str) -> bool:
    return (
        key in APP_CONFIG_SENSITIVE_KEYS
        or key.endswith(("_path", "_api_key"))
        or "token" in key
        or "private_key" in key
        or "credential" in key
        or "secret" in key
        or "password" in key
    )


def _safe_extract_zip(zip_bytes: bytes, destination: Path) -> None:
    """Extract a bounded ZIP after rejecting traversal, links, and oversized members."""
    if len(zip_bytes) > MAX_ZIP_BYTES:
        raise ValueError("ZIP exceeds compressed size limit")
    with zipfile.ZipFile(BytesIO(zip_bytes)) as archive:
        members = archive.infolist()
        if len(members) > MAX_ZIP_MEMBERS:
            raise ValueError("ZIP contains too many members")
        total_size = 0
        seen: set[PurePosixPath] = set()
        for member in members:
            if member.flag_bits & 0x1:
                raise ValueError("Encrypted ZIP members are not supported")
            if "\\" in member.filename:
                raise ValueError("ZIP member contains an unsafe path separator")
            relative = PurePosixPath(member.filename)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("ZIP member escapes the extraction directory")
            if relative in seen:
                raise ValueError("ZIP contains duplicate member paths")
            seen.add(relative)
            mode = member.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ValueError("ZIP symbolic links are not supported")
            if member.file_size > MAX_ZIP_MEMBER_BYTES:
                raise ValueError("ZIP member exceeds size limit")
            total_size += member.file_size
            if total_size > MAX_ZIP_UNCOMPRESSED_BYTES:
                raise ValueError("ZIP exceeds uncompressed size limit")

        extracted_size = 0
        for member in members:
            relative = PurePosixPath(member.filename)
            target = destination.joinpath(*relative.parts)
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as output:
                while chunk := source.read(64 * 1024):
                    extracted_size += len(chunk)
                    if (
                        extracted_size > MAX_ZIP_UNCOMPRESSED_BYTES
                        or output.tell() + len(chunk) > MAX_ZIP_MEMBER_BYTES
                    ):
                        raise ValueError("ZIP expanded beyond declared size limits")
                    output.write(chunk)


# Helper to translate package names
def get_db_package(package: str) -> str:
    """Convert URL-safe hyphenated iOS IDs (e.g., app-name-id123) to DB slash format (app-name/id123)."""
    if "-id" in package and not package.startswith("com."):
        return package.replace("-id", "/id")
    return package


def get_url_package(package: str) -> str:
    """Convert DB slash format (app-name/id123) to URL-safe hyphenated iOS IDs (app-name-id123)."""
    if "/id" in package:
        return package.replace("/id", "-id")
    return package


# Helper to get app metadata
def get_app_metadata(package: str) -> dict[str, Any] | None:
    url_pkg = get_url_package(package)
    apps = get_apps_config()
    for app in apps:
        if app.get("package_name") == url_pkg:
            return app
    return None


def _proposal_error_status(error: ProposalDataError) -> int:
    if error.code == "rulebook_missing":
        return 404
    if error.code.startswith("baseline_") or error.code == "listing_unchanged":
        return 409
    if error.code in {"listing_not_live", "listing_incomplete"}:
        return 503
    return 422


def _proposal_error(error: ProposalDataError) -> HTTPException:
    return HTTPException(
        status_code=_proposal_error_status(error),
        detail={"code": error.code, "message": str(error), "details": error.details},
    )


def _get_live_play_listing(package: str, language: str) -> ListingSnapshot:
    """Fetch the current live/draft listing for an app, regardless of platform."""
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


def _create_via_experiment_lifecycle(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Persist through the lifecycle-owned proposal boundary, never an HTTP handler."""
    from api_server.routes import experiments

    result = experiments.create_experiment_proposal(payload)
    if not isinstance(result, dict):
        raise TypeError("create_experiment_proposal must return a dictionary")
    return result


def _agent_cli_guidance(package: str) -> str:
    """Guidance shown in place of live LLM-backed chat/diagnostics.

    AI chat/diagnostics now happen in the user's coding-agent CLI session
    (Claude Code, Codex, etc.), which already has this project's MCP servers
    configured — there is no in-process LLM call left to make here.
    """
    return (
        "AI chat/diagnostics now happen in your coding-agent CLI session — it already has "
        "this project's MCP servers configured. Ask it directly, e.g. 'analyze the funnel "
        f"for {package} and show me an artifact.'"
    )


async def generate_app_diagnostic_live(package: str) -> str:
    return _agent_cli_guidance(package)


async def _run_agent_chat(package: str, _question: str) -> str:
    """Return guidance directing the user to their coding-agent CLI session."""
    return _agent_cli_guidance(package)


@router.get("/{package}/funnel")
def get_app_funnel(package: str, period: str = "30d") -> dict[str, Any]:
    """Funnel data from DB snapshot or live analysis fallback."""
    url_package = get_url_package(package)

    # Try reading pre-computed snapshot
    try:
        snap = get_latest_app_snapshot(DEFAULT_DB_PATH, url_package)
        if period == "30d" and snap and snap.get("raw_funnel_json"):
            return _enrich_funnel_response(
                json.loads(snap["raw_funnel_json"]),
                source="app_metrics_snapshots",
                captured_at=snap.get("data_as_of") or snap.get("created_at"),
                period=period,
                is_live=False,
            )
    except Exception as exc:
        logger.debug("Cached funnel snapshot unavailable", app=url_package, error=str(exc))

    # Fallback to live computation
    metadata = get_app_metadata(package)
    if not metadata:
        raise HTTPException(
            status_code=404, detail=f"App {package} not found in portfolio configuration"
        )
    category = metadata.get("app_category", "utilities")
    try:
        res_str = run_funnel_analysis(
            package_name=url_package, app_category=category, date_range=period
        )
        return _enrich_funnel_response(
            json.loads(res_str),
            source="funnel_engine_live",
            captured_at=datetime.now(UTC).isoformat(),
            period=period,
            is_live=True,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{package}/journeys")
def get_app_journeys(package: str) -> dict[str, Any]:
    """Journey definitions from EVENTS.md / journey map data."""
    try:
        db_package = get_db_package(package)
        url_package = get_url_package(package)
        fs_package = db_package.replace("/", "_")

        from app_manager.credential_store import get_app_credentials

        creds = get_app_credentials(url_package)

        # 1. Highest priority: explicit path from apps.json config
        if creds.events_md_path:
            p = Path(creds.events_md_path)
            if p.exists():
                return cast("dict[str, Any]", parse_events_md(str(p)))

        # 2. Pattern-based search
        project_root = Path(__file__).resolve().parent.parent.parent.parent
        possible_paths = [
            project_root / "docs" / f"{url_package}_EVENTS.md",
            project_root / f"{url_package}_EVENTS.md",
            project_root / "docs" / f"{fs_package}_EVENTS.md",
            project_root / f"{fs_package}_EVENTS.md",
        ]

        app_events_path = None
        for path in possible_paths:
            if path.exists():
                app_events_path = path
                break

        if app_events_path:
            return cast("dict[str, Any]", parse_events_md(str(app_events_path)))

        # 3. Dynamic GA4 event discovery fallback
        ga4_property = creds.ga4_property_id

        try:
            if creds.has_analytics():
                client = AnalyticsClient(
                    property_id=ga4_property, credentials_path=creds.google_credentials_path
                )
                report = client.get_events(start_date="30daysAgo", end_date="today", limit=50)
                events_list = report.events if hasattr(report, "events") else []
                events_list = sorted(
                    events_list, key=lambda x: x.get("total_users", 0), reverse=True
                )

                if events_list:
                    rows = []
                    for i, evt in enumerate(events_list):
                        evt_name = evt.get("event_name", "")
                        evt_count = evt.get("event_count", 0)
                        evt_users = evt.get("total_users", 0)
                        next_evt = (
                            events_list[i + 1].get("event_name", "—")
                            if i + 1 < len(events_list)
                            else "—"
                        )

                        rows.append(
                            {
                                "Step": str(i + 1),
                                "Screen / State": f"GA4 Event: {evt_name}",
                                "Event": evt_name,
                                "Branch": f"✅ {evt_count:,} events ({evt_users:,} users)",
                                "Next": next_evt,
                            }
                        )

                    return {
                        "journey_count": 1,
                        "journeys": {
                            "1": {
                                "id": 1,
                                "title": "Live GA4 Auto-Discovered Flow",
                                "description": f"This journey is dynamically constructed from GA4 events for property {ga4_property}.",
                                "sections": [
                                    {
                                        "section_title": "Auto-Discovered Events",
                                        "headers": [
                                            "Step",
                                            "Screen / State",
                                            "Event",
                                            "Branch",
                                            "Next",
                                        ],
                                        "rows": rows,
                                    }
                                ],
                            }
                        },
                    }
        except Exception as exc:
            logger.debug("GA4 journey discovery failed", app=url_package, error=str(exc))

        if not _demo_mode():
            return {
                "status": "unavailable",
                "journey_count": 0,
                "journeys": {},
                "provenance": {
                    "source": "unavailable",
                    "captured_at": datetime.now(UTC).isoformat(),
                    "is_live": False,
                },
                "unavailable_sources": ["events_md", "analytics"],
            }

        # Explicit demo mode only: representative events for UI demonstrations.
        mock_events = [
            {"event_name": "first_open", "event_count": 25000, "total_users": 15000},
            {"event_name": "session_start", "event_count": 48000, "total_users": 14500},
            {"event_name": "screen_view", "event_count": 120000, "total_users": 13800},
            {"event_name": "onboarding_complete", "event_count": 12000, "total_users": 8500},
            {"event_name": "paywall_viewed", "event_count": 9500, "total_users": 7200},
            {"event_name": "purchase", "event_count": 820, "total_users": 650},
            {"event_name": "app_exception", "event_count": 340, "total_users": 280},
        ]

        rows = []
        for i, evt in enumerate(mock_events):
            evt_name = evt["event_name"]
            evt_count = evt["event_count"]
            evt_users = evt["total_users"]
            next_evt = mock_events[i + 1]["event_name"] if i + 1 < len(mock_events) else "—"

            rows.append(
                {
                    "Step": str(i + 1),
                    "Screen / State": f"GA4 Event: {evt_name}",
                    "Event": evt_name,
                    "Branch": f"✅ {evt_count:,} events ({evt_users:,} users)",
                    "Next": next_evt,
                }
            )

        return {
            "journey_count": 1,
            "journeys": {
                "1": {
                    "id": 1,
                    "title": "Demo GA4 Event Flow",
                    "description": "Synthetic event flow enabled by MCP_GC_DEMO_MODE=1.",
                    "sections": [
                        {
                            "section_title": "Auto-Discovered Events",
                            "headers": ["Step", "Screen / State", "Event", "Branch", "Next"],
                            "rows": rows,
                        }
                    ],
                }
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{package}/events")
def get_app_events(package: str, period: str = "30d") -> dict[str, Any]:
    """GA4 event counts from analytics MCP."""
    url_package = get_url_package(package)
    from app_manager.credential_store import get_app_credentials

    creds = get_app_credentials(url_package)
    ga4_property = creds.ga4_property_id

    start_date = "30daysAgo"
    if period.endswith("d"):
        try:
            days = int(period[:-1])
            start_date = f"{days}daysAgo"
        except ValueError:
            pass

    try:
        client = AnalyticsClient(
            property_id=ga4_property, credentials_path=creds.google_credentials_path
        )
        report = client.get_events(start_date=start_date, end_date="today")
        return report.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{package}/revenue")
def get_app_revenue(package: str, period: str = "30d") -> dict[str, Any]:
    """Combined AdMob + RevenueCat + GA4 revenue from DB snapshot or live fallback."""
    url_package = get_url_package(package)

    # Try reading pre-computed snapshot — but skip it when the app has a GCS bucket
    # and the snapshot shows null RC (we want the live GCS fallback to run instead).
    from app_manager.credential_store import get_app_credentials as _get_creds

    _quick_creds = _get_creds(url_package)
    # Skip snapshot when we need live per-store RC data or live GCS data
    _needs_live = bool(
        (_quick_creds.gcs_play_console_bucket and not _quick_creds.has_revenuecat())
        or _quick_creds.rc_platform  # per-store RC filter requires live call
    )

    if not _needs_live and period == "30d":
        try:
            snap = get_latest_app_snapshot(DEFAULT_DB_PATH, url_package)
            if snap and snap.get("raw_revenue_json"):
                cached = cast("dict[str, Any]", json.loads(snap["raw_revenue_json"]))
                if cached.get("revenuecat") or cached.get("gcs_iap"):
                    return cached
        except Exception as exc:
            logger.debug("Cached revenue snapshot unavailable", app=url_package, error=str(exc))

    # Fallback to live computation
    from app_manager.credential_store import get_app_credentials

    creds = get_app_credentials(url_package)

    start_date, end_date = _parse_date_range(period)

    # 1. Fetch AdMob
    admob_metrics = None
    try:
        if creds.has_admob():
            from admob_mcp.client import AdMobClient

            admob = AdMobClient(
                account_id=creds.admob_account_id, credentials_path=creds.google_credentials_path
            )
            admob_metrics = _fetch_admob_metrics(admob, url_package)
    except Exception as exc:
        logger.debug("Live AdMob revenue unavailable", app=url_package, error=str(exc))

    # 2. Revenue: RevenueCat → GCS Play Console → App Store Connect → null
    rc_metrics = None
    gcs_revenue = None
    asc_revenue = None

    # 2a. RevenueCat (primary) — filtered by store when rc_platform is set
    try:
        if creds.has_revenuecat():
            from revenuecat_mcp.client import RevenueCatClient

            revenuecat = RevenueCatClient(
                api_key=creds.revenuecat_api_key, project_id=creds.revenuecat_project_id
            )
            rc_metrics = _fetch_revenuecat_metrics(revenuecat, store=creds.rc_platform)
    except Exception as exc:
        logger.debug("Live RevenueCat revenue unavailable", app=url_package, error=str(exc))

    # 2b. GCS Play Console earnings ZIP (Android fallback)
    if not rc_metrics and creds.gcs_play_console_bucket and creds.google_credentials_path:
        try:
            from app_manager.gcs_revenue_fetcher import fetch_play_console_revenue

            days_num = int(period[:-1]) if period.endswith("d") else 30
            gcs_revenue = fetch_play_console_revenue(
                credentials_path=creds.google_credentials_path,
                bucket_name=creds.gcs_play_console_bucket,
                package_name=url_package,
                days=days_num,
            )
        except Exception as exc:
            logger.debug("GCS revenue fallback unavailable", app=url_package, error=str(exc))

    # 2c. App Store Connect sales reports (iOS fallback)
    if not rc_metrics and not gcs_revenue and creds.has_app_store_connect():
        try:
            from datetime import UTC, datetime

            from app_manager.app_store_revenue_fetcher import fetch_app_store_revenue

            ym = datetime.now(UTC).strftime("%Y-%m")
            asc_revenue = fetch_app_store_revenue(creds, ym)
        except Exception as exc:
            logger.debug("App Store revenue fallback unavailable", app=url_package, error=str(exc))

    # 3. Fetch GA4
    ga4_rev = None
    try:
        if creds.has_analytics():
            analytics = AnalyticsClient(
                property_id=creds.ga4_property_id, credentials_path=creds.google_credentials_path
            )
            ga4_rev = _fetch_ga4_revenue(analytics, start_date, end_date)
    except Exception as exc:
        logger.debug("GA4 revenue unavailable", app=url_package, error=str(exc))

    # 4. Fetch Google Ads
    google_ads_metrics = None
    try:
        google_ads_config_path = creds.google_ads_config_path
        if creds.has_google_ads() and google_ads_config_path and creds.google_ads_customer_id:
            from app_manager.google_ads_fetcher import fetch_google_ads_metrics

            days = int(period[:-1]) if period.endswith("d") else 30
            google_ads_metrics = (
                fetch_google_ads_metrics(google_ads_config_path, creds.google_ads_customer_id, days)
                or None
            )
    except Exception as exc:
        logger.debug("Google Ads metrics unavailable", app=url_package, error=str(exc))

    return {
        "admob": admob_metrics,
        "revenuecat": rc_metrics,
        "gcs_iap": gcs_revenue,
        "app_store": asc_revenue,
        "ga4": ga4_rev,
        "google_ads": google_ads_metrics,
    }


@router.get("/{package}/storefront")
def get_app_storefront(package: str, period: str = "30d") -> dict[str, Any]:
    """Store performance from SQLite."""
    if period not in {"7d", "30d"}:
        raise HTTPException(status_code=422, detail="Storefront period must be 7d or 30d")
    try:
        db_package = get_db_package(package)
        country_data = get_country_performance(DEFAULT_DB_PATH, db_package)
        traffic_data = get_traffic_performance(DEFAULT_DB_PATH, db_package)
        search_data = get_search_performance(DEFAULT_DB_PATH, db_package)

        dated_rows = country_data + traffic_data + search_data
        valid_dates = []
        for row in dated_rows:
            try:
                valid_dates.append(date.fromisoformat(str(row.get("date", ""))))
            except ValueError:
                continue
        latest_source_date = max(valid_dates, default=None)
        period_days = int(period[:-1])
        period_start = (
            latest_source_date - timedelta(days=period_days - 1) if latest_source_date else None
        )

        def in_period(row: dict[str, Any]) -> bool:
            if period_start is None or latest_source_date is None:
                return False
            try:
                row_date = date.fromisoformat(str(row.get("date", "")))
            except ValueError:
                return False
            return period_start <= row_date <= latest_source_date

        country_data = [row for row in country_data if in_period(row)]
        traffic_data = [row for row in traffic_data if in_period(row)]
        search_data = [row for row in search_data if in_period(row)]

        watermarks = get_source_watermarks(DEFAULT_DB_PATH, db_package)
        watermark = next((row for row in watermarks if row["source"] == "storefront"), None)
        status = watermark["last_status"] if watermark else "unavailable"
        return {
            "country": country_data,
            "traffic_source": traffic_data,
            "search_term": search_data,
            "status": status,
            "as_of": latest_source_date.isoformat() if latest_source_date else None,
            "freshness": watermark.get("last_completed_at") if watermark else None,
            "record_count": watermark.get("record_count", 0) if watermark else 0,
            "provenance": {
                "source": "play_console_gcs_store_performance" if watermark else "unavailable",
                "captured_at": watermark.get("last_completed_at") if watermark else None,
                "period": period,
                "period_start": period_start.isoformat() if period_start else None,
                "period_end": latest_source_date.isoformat() if latest_source_date else None,
                "is_live": False,
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{package}/store-conversion/proposals")
async def create_store_conversion_proposal(
    package: str, data: StoreConversionProposalRequest
) -> dict[str, Any]:
    """Create an evidence-backed Play listing experiment proposal."""
    url_package = get_url_package(package)
    if get_db_package(package) != url_package:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "unsupported_store",
                "message": "Store conversion proposals currently support Google Play apps only",
                "details": {},
            },
        )

    try:
        rulebook, rulebook_path = load_rulebook(url_package, project_root=PROJECT_ROOT)
        current_listing = _get_live_play_listing(url_package, data.language)
        country_rows = get_country_performance(DEFAULT_DB_PATH, url_package)

        generated_listing = None
        if data.proposed_listing is None:
            strategy = rulebook.get("aso_strategy", {})
            target_keywords = (
                strategy.get("target_keywords", []) if isinstance(strategy, dict) else []
            )
            if not isinstance(target_keywords, list) or not all(
                isinstance(keyword, str) for keyword in target_keywords
            ):
                raise ProposalDataError(
                    "Rulebook target_keywords must be a string list",
                    code="rulebook_invalid",
                )
            generated = ASOClient().generate_optimized_listing(
                package_name=url_package,
                target_keywords=target_keywords,
                language=data.language.split("-", 1)[0],
                country=data.country.lower(),
            )
            generated_listing = ListingText(
                title=generated.suggested_title,
                short_description=generated.suggested_short_description,
                full_description=generated.suggested_description,
            )

        proposal = build_store_conversion_proposal(
            package=url_package,
            request=data,
            country_rows=country_rows,
            current_listing=current_listing,
            rulebook=redact_rulebook(rulebook),
            rulebook_source=f"rulebooks/{rulebook_path.name}",
            generated_listing=generated_listing,
        )
        lifecycle = submit_store_conversion_proposal(
            proposal,
            _create_via_experiment_lifecycle,
        )
        experiment = dict(lifecycle)
        auto_executed = False
        if data.execution_mode == "auto_low_risk":
            from api_server.routes import experiments

            experiment = await experiments.auto_advance_experiment_proposal(experiment["id"])
            auto_executed = experiment.get("status") == "measuring"
        validation = experiment.get("validation")
        return {
            "proposal": proposal.model_dump(mode="json"),
            "experiment": experiment,
            "validation": validation,
            "auto_executed": auto_executed,
            "requires_review": (data.execution_mode != "recommend_only" and not auto_executed),
        }
    except ProposalDataError as exc:
        raise _proposal_error(exc)
    except ValidationError:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "listing_invalid",
                "message": "The generated listing violates deterministic Play text limits",
                "details": {},
            },
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Store conversion proposal creation failed", app=url_package)
        raise HTTPException(
            status_code=503,
            detail={
                "code": "proposal_source_unavailable",
                "message": "A required live proposal source is unavailable",
                "details": {"error_type": type(exc).__name__},
            },
        )


@router.get("/{package}/reviews")
def get_app_reviews(package: str, stage: str | None = None) -> list[dict[str, Any]]:
    """Reviews from Play Store MCP or App Store Connect MCP."""
    try:
        if "-id" in package and not package.startswith("com."):
            # iOS reviews via AppStoreClient
            from app_store_mcp.client import AppStoreClient

            app_store_client = AppStoreClient()
            app_store_reviews = app_store_client.get_reviews(bundle_id=package, max_results=50)

            stage_keywords = {
                "onboarding": ["onboarding", "login", "register", "start", "tutorial", "welcome"],
                "dashboard": ["dashboard", "home", "main", "navigation"],
                "core_calculator": [
                    "calculate",
                    "emi",
                    "loan",
                    "interest",
                    "calculator",
                    "compute",
                ],
                "paywall": [
                    "paywall",
                    "premium",
                    "subscribe",
                    "buy",
                    "purchase",
                    "trial",
                    "price",
                    "cost",
                ],
            }

            filtered_reviews = []
            keywords = stage_keywords.get(stage.lower(), []) if stage else []

            for app_store_review in app_store_reviews:
                match = True
                comment = app_store_review.get("comment", "")
                if keywords:
                    comment_lower = comment.lower()
                    match = any(kw in comment_lower for kw in keywords)

                if match:
                    filtered_reviews.append(
                        {
                            "review_id": app_store_review.get("review_id", ""),
                            "author_name": app_store_review.get("author_name", ""),
                            "star_rating": app_store_review.get("star_rating", 5),
                            "comment": comment,
                            "language": app_store_review.get("language", "en"),
                            "device": "iOS Device",
                            "android_version": "iOS",
                            "app_version_name": app_store_review.get("app_version_name", ""),
                            "last_modified": app_store_review.get("last_modified"),
                            "developer_reply": None,
                            "developer_reply_time": None,
                        }
                    )
            return filtered_reviews[:5]

        # Android reviews
        try:
            play_store_client = PlayStoreClient()
            play_store_reviews = play_store_client.get_reviews(package_name=package, max_results=50)
        except Exception as e:
            from structlog import get_logger

            get_logger(__name__).warning(
                "Failed to fetch reviews from Play Store. Returning empty list.", error=str(e)
            )
            play_store_reviews = []

        stage_keywords = {
            "onboarding": ["onboarding", "login", "register", "start", "tutorial", "welcome"],
            "dashboard": ["dashboard", "home", "main", "navigation"],
            "core_calculator": ["calculate", "emi", "loan", "interest", "calculator", "compute"],
            "paywall": [
                "paywall",
                "premium",
                "subscribe",
                "buy",
                "purchase",
                "trial",
                "price",
                "cost",
            ],
        }

        filtered_reviews = []
        keywords = stage_keywords.get(stage.lower(), []) if stage else []

        for play_store_review in play_store_reviews:
            match = True
            if keywords:
                comment_lower = play_store_review.comment.lower()
                match = any(kw in comment_lower for kw in keywords)

            if match:
                filtered_reviews.append(
                    {
                        "review_id": play_store_review.review_id,
                        "author_name": play_store_review.author_name,
                        "star_rating": play_store_review.star_rating,
                        "comment": play_store_review.comment,
                        "language": play_store_review.language,
                        "device": play_store_review.device,
                        "android_version": play_store_review.android_version,
                        "app_version_name": play_store_review.app_version_name,
                        "last_modified": play_store_review.last_modified.isoformat()
                        if play_store_review.last_modified
                        else None,
                        "developer_reply": play_store_review.developer_reply,
                        "developer_reply_time": play_store_review.developer_reply_time.isoformat()
                        if play_store_review.developer_reply_time
                        else None,
                    }
                )

        return filtered_reviews[:5]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{package}/reviews/analysis")
def get_app_reviews_analysis(package: str) -> dict[str, Any]:
    """Generates a structured sentiment and keyword analysis from Play Store or App Store reviews."""
    try:
        reviews: list[ReviewAnalysisRow] = []
        if "-id" in package and not package.startswith("com."):
            # iOS reviews via AppStoreClient
            from app_store_mcp.client import AppStoreClient

            try:
                app_store_client = AppStoreClient()
                app_store_reviews = app_store_client.get_reviews(bundle_id=package, max_results=50)
                for app_store_review in app_store_reviews:
                    reviews.append(
                        {
                            "rating": cast("int", app_store_review.get("star_rating", 5)),
                            "comment": cast("str", app_store_review.get("comment", "")),
                        }
                    )
            except Exception as exc:
                logger.debug("App Store review analysis unavailable", app=package, error=str(exc))
        else:
            # Android reviews
            try:
                play_store_client = PlayStoreClient()
                play_store_reviews = play_store_client.get_reviews(
                    package_name=package, max_results=50
                )
                for play_store_review in play_store_reviews:
                    reviews.append(
                        {
                            "rating": play_store_review.star_rating,
                            "comment": play_store_review.comment,
                        }
                    )
            except Exception as exc:
                logger.debug("Play Store review analysis unavailable", app=package, error=str(exc))

        # If no reviews, return default analysis structure
        if not reviews:
            return {
                "average_rating": 0.0,
                "total_reviews": 0,
                "distribution": {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0},
                "sentiment": {"positive": 0, "neutral": 0, "negative": 0},
                "stage_correlation": {
                    "onboarding": {"count": 0, "rating": 0, "reviews": []},
                    "dashboard": {"count": 0, "rating": 0, "reviews": []},
                    "core_calculator": {"count": 0, "rating": 0, "reviews": []},
                    "paywall": {"count": 0, "rating": 0, "reviews": []},
                },
                "keywords": [],
            }

        ratings = [r["rating"] for r in reviews]
        avg_rating = round(sum(ratings) / len(ratings), 2)

        dist = {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}
        for rating in ratings:
            r_str = str(rating)
            if r_str in dist:
                dist[r_str] += 1

        sent = {"positive": 0, "neutral": 0, "negative": 0}
        for rating in ratings:
            if rating >= 4:
                sent["positive"] += 1
            elif rating == 3:
                sent["neutral"] += 1
            else:
                sent["negative"] += 1

        # Percentages
        total = len(reviews)
        sent_pct = {
            "positive": round((sent["positive"] / total) * 100, 1),
            "neutral": round((sent["neutral"] / total) * 100, 1),
            "negative": round((sent["negative"] / total) * 100, 1),
        }

        stage_keywords = {
            "onboarding": [
                "onboarding",
                "login",
                "register",
                "start",
                "tutorial",
                "welcome",
                "otp",
                "sign up",
                "sign in",
            ],
            "dashboard": ["dashboard", "home", "main", "navigation", "menu"],
            "core_calculator": [
                "calculate",
                "emi",
                "loan",
                "interest",
                "calculator",
                "compute",
                "result",
                "calculation",
            ],
            "paywall": [
                "paywall",
                "premium",
                "subscribe",
                "buy",
                "purchase",
                "trial",
                "price",
                "cost",
                "ads",
                "ad",
                "commercials",
                "money",
                "pay",
            ],
        }

        stage_corr: dict[str, StageCorrelation] = {
            "onboarding": {"count": 0, "rating_sum": 0, "reviews": []},
            "dashboard": {"count": 0, "rating_sum": 0, "reviews": []},
            "core_calculator": {"count": 0, "rating_sum": 0, "reviews": []},
            "paywall": {"count": 0, "rating_sum": 0, "reviews": []},
        }

        # Keyword extraction helpers
        issue_keywords = [
            "ads",
            "ad",
            "commercials",
            "crash",
            "slow",
            "bug",
            "freeze",
            "hang",
            "expensive",
            "waste",
            "useless",
            "scam",
            "cheat",
            "login",
            "register",
            "payment",
        ]
        praise_keywords = [
            "good",
            "nice",
            "excellent",
            "love",
            "best",
            "great",
            "useful",
            "helpful",
            "easy",
            "simple",
            "fast",
            "awesome",
            "perfect",
            "recommend",
        ]

        kw_counts: dict[str, KeywordCount] = {}
        for review in reviews:
            comment_lower = review["comment"].lower()
            rating = review["rating"]

            # Check stage correlation
            for stage, kws in stage_keywords.items():
                if any(kw in comment_lower for kw in kws):
                    stage_corr[stage]["count"] += 1
                    stage_corr[stage]["rating_sum"] += rating
                    # Add excerpt (up to 3)
                    if len(stage_corr[stage]["reviews"]) < 3:
                        stage_corr[stage]["reviews"].append(
                            {
                                "author_name": "User",
                                "rating": rating,
                                "comment": review["comment"].strip(),
                            }
                        )

            # Count keyword frequencies
            for kw in issue_keywords + praise_keywords:
                if kw in comment_lower:
                    sentiment_type = "negative" if kw in issue_keywords else "positive"
                    if kw not in kw_counts:
                        kw_counts[kw] = {"keyword": kw, "count": 0, "sentiment": sentiment_type}
                    kw_counts[kw]["count"] += 1

        # Finalize stage correlation response structure
        stage_corr_final = {}
        for stage, data in stage_corr.items():
            avg_stage_rating = (
                round(data["rating_sum"] / data["count"], 2) if data["count"] > 0 else 0.0
            )
            stage_corr_final[stage] = {
                "count": data["count"],
                "rating": avg_stage_rating,
                "reviews": data["reviews"],
            }

        # Sort keywords by frequency
        sorted_kws = sorted(kw_counts.values(), key=lambda x: x["count"], reverse=True)[:10]

        return {
            "average_rating": avg_rating,
            "total_reviews": total,
            "distribution": dist,
            "sentiment": sent_pct,
            "stage_correlation": stage_corr_final,
            "keywords": sorted_kws,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{package}/keywords")
def get_app_keywords(package: str) -> list[dict[str, Any]]:
    """Keyword positions from ASO MCP."""
    try:
        aso_client = ASOClient()
        metadata = get_app_metadata(package)
        rulebook = None
        if metadata:
            config = AppManagerConfig(package_name=package)
            rulebook = config.get_rulebook()

        target_keywords = []
        if rulebook:
            target_keywords = rulebook.get("aso_strategy", {}).get("target_keywords", [])

        if not target_keywords:
            target_keywords = ["calculator", "emi", "loan"]

        rankings = []
        for kw in target_keywords:
            try:
                rank_res = aso_client.track_keyword_ranking(keyword=kw, package_name=package)
                difficulty_res = aso_client.get_keyword_difficulty(keyword=kw)

                # Fetch volume using ASO client volume method
                volume_res = aso_client.get_keyword_volume([kw])
                volume_score = 50  # default fallback
                if volume_res and len(volume_res) > 0:
                    raw_vol = volume_res[0].estimated_volume
                    # Cap volume at 100 for progress bar compatibility in the UI
                    if raw_vol > 100:
                        if raw_vol > 100000:
                            volume_score = 95
                        elif raw_vol > 10000:
                            volume_score = 80
                        elif raw_vol > 1000:
                            volume_score = 65
                        else:
                            volume_score = min(100, int(raw_vol / 10))
                        volume_score = max(10, volume_score)
                    else:
                        volume_score = raw_vol

                rankings.append(
                    {
                        "keyword": kw,
                        "rank": rank_res.rank,
                        "found": rank_res.was_found,
                        "volume": volume_score,
                        "difficulty": min(100.0, difficulty_res.difficulty_score)
                        if hasattr(difficulty_res, "difficulty_score")
                        else 30,
                        "difficulty_label": difficulty_res.difficulty_label
                        if hasattr(difficulty_res, "difficulty_label")
                        else "Medium",
                        "rank_change": 0,
                    }
                )
            except Exception:
                rankings.append(
                    {
                        "keyword": kw,
                        "rank": None,
                        "found": False,
                        "volume": 0,
                        "difficulty": 0,
                        "difficulty_label": "Unknown",
                        "rank_change": 0,
                    }
                )
        return rankings
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class KeywordsUpdate(BaseModel):
    keywords: list[str]


@router.put("/{package}/keywords")
def update_app_keywords(package: str, data: KeywordsUpdate) -> dict[str, Any]:
    """Update target keywords in rulebooks/{package}.yaml."""
    if not config_writes_enabled():
        raise HTTPException(status_code=403, detail="Configuration writes are disabled")
    url_package = get_url_package(package)
    rulebook_path = PROJECT_ROOT / "rulebooks" / f"{url_package}.yaml"

    import yaml

    if not rulebook_path.exists():
        rulebook = {"package_name": url_package, "aso_strategy": {"target_keywords": data.keywords}}
    else:
        try:
            with rulebook_path.open("r", encoding="utf-8") as f:
                rulebook = cast("dict[str, Any]", yaml.safe_load(f) or {})
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to read rulebook: {e}")

        if "aso_strategy" not in rulebook:
            rulebook["aso_strategy"] = {}
        strategy = cast("dict[str, Any]", rulebook["aso_strategy"])
        strategy["target_keywords"] = data.keywords

    try:
        rulebook_path.parent.mkdir(parents=True, exist_ok=True)
        with rulebook_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(rulebook, f, sort_keys=False, allow_unicode=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save rulebook: {e}")

    return {"success": True, "keywords": data.keywords}


@router.get("/{package}/rulebook")
def get_app_rulebook(package: str) -> dict[str, Any]:
    """Return normalized UI policy plus the redacted source rulebook."""
    url_package = get_url_package(package)
    try:
        rulebook, path = load_rulebook(url_package, project_root=PROJECT_ROOT)
        redacted = redact_rulebook(rulebook)
        raw_constraints = redacted.get("metadata_constraints") or {}
        constraints: dict[str, Any] = {}
        prohibited_terms: list[str] = []
        for field in ("title", "short_description", "full_description"):
            raw = raw_constraints.get(field) or {}
            prohibited = list(raw.get("prohibited_keywords") or [])
            prohibited_terms.extend(str(term) for term in prohibited)
            constraints[field] = {
                "max_length": raw.get("max_length"),
                "min_length": raw.get("min_length"),
                "required": raw.get("required", True),
                "required_terms": list(raw.get("required_keywords") or []),
                "prohibited_terms": prohibited,
            }
        policy = redacted.get("experiment_policy") or redacted.get("execution_policy") or {}
        safety = redacted.get("safety_rules") or {}
        max_mode = (
            "manual"
            if safety.get("require_telegram_approval") or safety.get("require_manual_approval")
            else policy.get("max_execution_mode")
            or policy.get("max_mode")
            or redacted.get("max_execution_mode")
            or "auto_low_risk"
        )
        mode_order = ["recommend_only", "manual", "auto_low_risk"]
        if max_mode not in mode_order:
            max_mode = "recommend_only"
        version = redacted.get("version") or redacted.get("last_updated")
        provenance = {
            "source": f"rulebooks/{path.name}",
            "is_live": False,
            "captured_at": version,
            "reference": url_package,
        }
        return {
            "package_name": url_package,
            "version": version,
            "updated_at": redacted.get("last_updated"),
            "target_keywords": list(
                (redacted.get("aso_strategy") or {}).get("target_keywords") or []
            ),
            "constraints": constraints,
            "forbidden_terms": sorted(set(prohibited_terms)),
            "allowed_autonomy_modes": mode_order[: mode_order.index(max_mode) + 1],
            "provenance": provenance,
            "raw_rulebook": redacted,
        }
    except ProposalDataError as exc:
        raise _proposal_error(exc)


@router.get("/{package}/listing/{language}")
def get_app_listing(package: str, language: str) -> dict[str, Any]:
    """Current listing from Play Store MCP or App Store Connect MCP."""
    try:
        if "-id" in package and not package.startswith("com."):
            # iOS listing details via AppStoreClient
            from app_store_mcp.client import AppStoreClient

            app_store_client = AppStoreClient()
            app_store_details = app_store_client.get_app_details(
                bundle_id=package, language=language
            )
            return {
                "title": app_store_details.get("title", ""),
                "short_description": app_store_details.get("short_description", ""),
                "full_description": app_store_details.get("full_description", ""),
                "default_language": app_store_details.get("default_language", "en-US"),
                "locale": language,
                "fetched_at": datetime.now(UTC).isoformat(),
                "provenance": {
                    "source": "itunes_public_api_or_client_fallback",
                    "live": False,
                    "is_live": False,
                    "retrieved_at": datetime.now(UTC).isoformat(),
                    "captured_at": datetime.now(UTC).isoformat(),
                },
            }

        try:
            credentials = get_app_credentials(get_url_package(package))
            if not credentials.has_play_store():
                raise RuntimeError("Play Store credentials are not configured for this app")
            play_store_client = PlayStoreClient(
                credentials_path=credentials.google_credentials_path
            )
            play_store_details = play_store_client.get_app_details(
                package_name=package, language=language
            )
            return {
                "title": play_store_details.title,
                "short_description": play_store_details.short_description,
                "full_description": play_store_details.full_description,
                "default_language": play_store_details.default_language,
                "locale": language,
                "fetched_at": datetime.now(UTC).isoformat(),
                "provenance": {
                    "source": "google_play_developer_api",
                    "live": True,
                    "is_live": True,
                    "retrieved_at": datetime.now(UTC).isoformat(),
                    "captured_at": datetime.now(UTC).isoformat(),
                },
            }
        except Exception as e:
            from structlog import get_logger

            get_logger(__name__).warning(
                "Failed to fetch app details from Play Store. Returning labeled fallback listing.",
                error=str(e),
            )
            if not _demo_mode():
                return {
                    "status": "unavailable",
                    "title": None,
                    "short_description": None,
                    "full_description": None,
                    "default_language": None,
                    "locale": language,
                    "fetched_at": datetime.now(UTC).isoformat(),
                    "provenance": {
                        "source": "unavailable",
                        "live": False,
                        "is_live": False,
                        "retrieved_at": datetime.now(UTC).isoformat(),
                        "captured_at": datetime.now(UTC).isoformat(),
                    },
                }
            return {
                "status": "demo",
                "title": package.split(".")[-1].replace("_", " ").title(),
                "short_description": "Demo short description.",
                "full_description": "Demo full description enabled by MCP_GC_DEMO_MODE=1.",
                "default_language": "en-US",
                "locale": language,
                "fetched_at": datetime.now(UTC).isoformat(),
                "provenance": {
                    "source": "explicit_demo_fallback",
                    "live": False,
                    "is_live": False,
                    "retrieved_at": datetime.now(UTC).isoformat(),
                    "captured_at": datetime.now(UTC).isoformat(),
                },
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{package}/admob_timeline")
def get_admob_timeline(package: str, days: int = 30) -> dict[str, Any]:
    """Real daily AdMob revenue from get_network_report(dimensions=['DATE'])."""
    from datetime import UTC, datetime, timedelta

    url_package = get_url_package(package)
    from app_manager.credential_store import get_app_credentials

    creds = get_app_credentials(url_package)
    if not creds.has_admob():
        return {"daily": []}
    try:
        from admob_mcp.client import AdMobClient

        admob = AdMobClient(
            account_id=creds.admob_account_id, credentials_path=creds.google_credentials_path
        )
        end_dt = datetime.now(UTC)
        start_dt = end_dt - timedelta(days=days)
        # Find the AdMob app_id for this package
        app_id_filter = None
        try:
            admob_apps = admob.list_apps()
            matched = next((a for a in admob_apps if a.linked_app_store_id == url_package), None)
            if matched:
                app_id_filter = [{"dimension": "APP", "matchesAny": {"values": [matched.app_id]}}]
        except Exception as exc:
            logger.debug("Unable to resolve AdMob app filter", app=url_package, error=str(exc))

        report = admob.get_network_report(
            start_date=start_dt.strftime("%Y-%m-%d"),
            end_date=end_dt.strftime("%Y-%m-%d"),
            dimensions=["DATE"],
            metrics=["ESTIMATED_EARNINGS", "IMPRESSIONS", "CLICKS"],
            dimension_filters=app_id_filter,
        )
        daily = []
        for row in report.rows:
            date_val = row.dimensions.get("DATE", "")
            daily.append(
                {
                    "date": date_val,
                    "revenue": row.metrics.get("ESTIMATED_EARNINGS", 0),
                    "impressions": row.metrics.get("IMPRESSIONS", 0),
                    "clicks": row.metrics.get("CLICKS", 0),
                }
            )
        return {"daily": sorted(daily, key=lambda x: x["date"])}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{package}/ads")
def get_app_ads(package: str, period: str = "30d") -> dict[str, Any]:
    """Google Ads campaign metrics for the given app."""
    url_package = get_url_package(package)
    from app_manager.credential_store import get_app_credentials

    creds = get_app_credentials(url_package)
    google_ads_config_path = creds.google_ads_config_path
    if not creds.has_google_ads() or not google_ads_config_path or not creds.google_ads_customer_id:
        return {"google_ads": None}
    try:
        from app_manager.google_ads_fetcher import fetch_google_ads_metrics

        days = int(period[:-1]) if period.endswith("d") else 30
        data = fetch_google_ads_metrics(google_ads_config_path, creds.google_ads_customer_id, days)
        return {"google_ads": data or None}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class AppConfigUpdate(BaseModel):
    fields: dict[str, Any]


@router.get("/{package}/config")
def get_app_config(package: str) -> dict[str, Any]:
    """Return app configuration with secrets and local paths masked."""
    url_package = get_url_package(package)
    apps = _load_apps_config()
    entry = next((a for a in apps if a.get("package_name") == url_package), None)
    if not entry:
        raise HTTPException(
            status_code=404, detail=f"App {url_package} not found in portfolio configuration"
        )
    return {
        key: MASKED_VALUE if _is_sensitive_app_config(key) and value else value
        for key, value in entry.items()
    }


@router.post("/{package}/experiment-recommendations")
def recommend_app_experiments(
    package: str, data: ExperimentRecommendationRequest
) -> dict[str, Any]:
    """Recommend complete experiment designs from observed MCP funnel evidence."""
    url_package = get_url_package(package)
    metadata = get_app_metadata(package)
    if not metadata:
        raise HTTPException(status_code=404, detail=f"App {package} not found in portfolio")

    funnel: dict[str, Any] = {}
    captured_at: str | None = None
    snapshot_source = "cached_mcp_snapshot"
    if not data.refresh_live:
        snapshot = get_latest_app_snapshot(DEFAULT_DB_PATH, url_package)
        if snapshot and snapshot.get("raw_funnel_json"):
            try:
                parsed = json.loads(snapshot["raw_funnel_json"])
                if isinstance(parsed, dict):
                    funnel = parsed
                    captured_at = snapshot.get("data_as_of") or snapshot.get("created_at")
            except (TypeError, json.JSONDecodeError):
                funnel = {}

    if not funnel:
        try:
            funnel = json.loads(
                run_funnel_analysis(
                    package_name=url_package,
                    app_category=metadata.get("app_category", "utilities"),
                    date_range="30d",
                )
            )
            captured_at = datetime.now(UTC).isoformat()
            snapshot_source = "live_mcp_refresh"
        except Exception as exc:
            logger.warning(
                "Experiment recommendation data unavailable",
                app=url_package,
                error_type=type(exc).__name__,
            )
            raise HTTPException(
                status_code=409,
                detail="No observed MCP funnel evidence is available for experiment recommendations",
            )

    active_types = {
        str(experiment["experiment_type"])
        for experiment in get_db_experiments(DEFAULT_DB_PATH, app_package=url_package)
        if experiment.get("status") in {"approved", "active", "measuring", "rolling_back"}
    }
    result = recommend_experiment_designs(
        package_name=url_package,
        funnel=funnel,
        captured_at=captured_at,
        focus=data.focus,
        max_results=data.max_results,
        active_experiment_types=active_types,
    )
    result["snapshot_source"] = snapshot_source
    if not result["recommendations"]:
        result["message"] = "No observed below-benchmark funnel stage matched the selected focus."
    return result


@router.put("/{package}/config")
def update_app_config(package: str, data: AppConfigUpdate) -> dict[str, bool]:
    """Update the apps.json entry for the given package."""
    if not config_writes_enabled():
        raise HTTPException(status_code=403, detail="Configuration writes are disabled")
    url_package = get_url_package(package)
    apps_config_path = PROJECT_ROOT / "config" / "apps.json"
    try:
        full = json.loads(apps_config_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read apps.json: {e}")
    apps = full.get("apps", [])
    idx = next((i for i, a in enumerate(apps) if a.get("package_name") == url_package), None)
    if idx is None:
        raise HTTPException(
            status_code=404, detail=f"App {url_package} not found in portfolio configuration"
        )
    unknown = sorted(set(data.fields) - APP_CONFIG_WRITABLE_KEYS)
    if unknown:
        raise HTTPException(
            status_code=422, detail=f"Unsupported app configuration keys: {unknown}"
        )
    updates = {key: value for key, value in data.fields.items() if value != MASKED_VALUE}
    apps[idx].update(updates)
    try:
        apps_config_path.write_text(
            json.dumps(full, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write apps.json: {e}")
    return {"success": True}


class ChatRequest(BaseModel):
    question: str


@router.post("/{package}/events_md/generate")
async def generate_events_md(
    package: str, zip_file: UploadFile = FastAPIFile(...)
) -> dict[str, Any]:
    """Upload a codebase ZIP → AI scans for analytics events → generates EVENTS.md."""
    if not config_writes_enabled():
        raise HTTPException(status_code=403, detail="Configuration writes are disabled")
    import tempfile

    url_package = get_url_package(package)
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    docs_dir = project_root / "docs"
    docs_dir.mkdir(exist_ok=True)
    output_path = docs_dir / f"{url_package}_EVENTS.md"

    # 1. Extract ZIP to temp directory
    try:
        zip_bytes = await zip_file.read(MAX_ZIP_BYTES + 1)
        if len(zip_bytes) > MAX_ZIP_BYTES:
            raise HTTPException(status_code=413, detail="ZIP exceeds compressed size limit")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to read ZIP: {exc}")

    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            _safe_extract_zip(zip_bytes, Path(tmp_dir))

            # 2. Collect relevant source files
            extensions = {".kt", ".java", ".swift", ".m", ".tsx", ".ts", ".js", ".py", ".xml"}
            priority_keywords = {
                "logEvent",
                "analytics",
                "Analytics",
                "FirebaseAnalytics",
                "Activity",
                "Fragment",
                "Screen",
                "ViewController",
                "trackEvent",
                "event_name",
                "EventName",
            }
            all_files: list[tuple[int, Path]] = []

            for path in Path(tmp_dir).rglob("*"):
                if not path.is_file() or path.suffix.lower() not in extensions:
                    continue
                # Score by keyword relevance
                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                    score = sum(1 for kw in priority_keywords if kw in text)
                    all_files.append((score, path))
                except Exception as exc:
                    logger.debug("Skipping unreadable source file", path=str(path), error=str(exc))

            # Sort by score descending, take top 80
            all_files.sort(key=lambda x: x[0], reverse=True)
            top_files = all_files[:80]

            # 3. Build code context (truncated to ~120k chars)
            MAX_CHARS = 120_000
            code_chunks: list[str] = []
            total = 0
            for _, fp in top_files:
                try:
                    content = fp.read_text(encoding="utf-8", errors="ignore")
                    rel = str(fp.relative_to(tmp_dir))
                    chunk = f"\n\n### FILE: {rel}\n```\n{content[:8000]}\n```"
                    if total + len(chunk) > MAX_CHARS:
                        break
                    code_chunks.append(chunk)
                    total += len(chunk)
                except Exception as exc:
                    logger.debug(
                        "Skipping source file during prompt assembly",
                        path=str(fp),
                        error=str(exc),
                    )

            code_context = "".join(code_chunks)

    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Invalid ZIP file")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to extract ZIP: {exc}")

    # 4. Load the EVENTS.md format template
    template_path = project_root / "docs" / "EVENTS.md"
    template = ""
    if template_path.exists():
        template = template_path.read_text(encoding="utf-8")[:4000]

    # 5. Build prompt for the AI agent
    prompt = f"""You are analyzing the source code of the app '{url_package}'.

Below are the key source files. Your task is to generate an EVENTS.md file that documents the complete user journey map, mapping each screen/state to its Firebase/GA4 analytics events.

## FORMAT TEMPLATE (follow this exact structure):
{template}

## SOURCE CODE:
{code_context}

## INSTRUCTIONS:
1. Find all Firebase/GA4 analytics event tracking calls (logEvent, FirebaseAnalytics, etc.)
2. Identify the main user journeys (Onboarding, Core Feature, Paywall, Settings, etc.)
3. For each journey, create a markdown table with columns: Step | Screen / State | Event | Branch | Next
4. Use the branch symbols from the template (✅ ⚠️ ⏭️ 💰 etc.)
5. Reference actual source file paths where events are fired

Output ONLY the markdown content for the EVENTS.md file. Start with the app name header. No explanations outside the markdown."""

    # 6. Call the coordinator agent
    try:
        generated_md = await _run_agent_chat(url_package, prompt)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"AI generation failed: {exc}")

    if not generated_md or len(generated_md) < 100:
        raise HTTPException(status_code=500, detail="AI returned insufficient content")

    # 7. Save the generated EVENTS.md
    try:
        output_path.write_text(generated_md, encoding="utf-8")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save EVENTS.md: {exc}")

    # 8. Update apps.json with the new path
    apps_config_path = project_root / "config" / "apps.json"
    try:
        full = json.loads(apps_config_path.read_text(encoding="utf-8"))
        for app in full.get("apps", []):
            if app.get("package_name") == url_package:
                app["events_md_path"] = str(output_path)
                break
        apps_config_path.write_text(
            json.dumps(full, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as exc:
        logger.warning("Generated EVENTS.md but failed to update apps config", error=str(exc))

    # 9. Parse to count journeys
    try:
        parsed = parse_events_md(str(output_path))
        journey_count = parsed.get("journey_count", 0)
    except Exception:
        journey_count = 0

    return {
        "path": str(output_path),
        "journey_count": journey_count,
        "preview": generated_md[:500],
        "app": url_package,
    }


@router.post("/{package}/chat")
async def app_chat(package: str, data: ChatRequest) -> dict[str, str]:
    """Ask the AI coordinator agent a freeform question about this app."""
    url_package = get_url_package(package)
    answer = await _run_agent_chat(url_package, data.question.strip())
    return {"answer": answer, "app": url_package}


@router.get("/{package}/retention")
def get_app_retention(package: str, days: int = 30) -> dict[str, Any]:
    """Daily new vs returning users from GA4 + D1/D7 from latest snapshot."""
    url_package = get_url_package(package)
    from app_manager.credential_store import get_app_credentials

    creds = get_app_credentials(url_package)

    # Pull D1/D7 from snapshot (fast)
    snap = get_latest_app_snapshot(DEFAULT_DB_PATH, url_package)
    d1 = snap.get("d1_retention") if snap else None
    d7 = snap.get("d7_retention") if snap else None

    if not creds.has_analytics():
        return {"cohorts": [], "d1": d1, "d7": d7}

    try:
        client = AnalyticsClient(
            property_id=creds.ga4_property_id,
            credentials_path=creds.google_credentials_path,
        )
        report = client.get_retention(
            start_date=f"{days}daysAgo",
            end_date="today",
        )
        return {"cohorts": report.cohorts, "d1": d1, "d7": d7}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{package}/diagnostic")
async def get_app_diagnostic(package: str) -> dict[str, str]:
    """Latest LLM-generated diagnostic narrative."""
    url_package = get_url_package(package)
    try:
        # Try reading pre-computed funnel summary from snapshot first
        snap = get_latest_app_snapshot(DEFAULT_DB_PATH, url_package)
        if snap and snap.get("raw_funnel_json"):
            funnel_data = json.loads(snap["raw_funnel_json"])
            if funnel_data.get("summary"):
                return {"diagnostic": funnel_data["summary"]}
    except Exception as exc:
        logger.debug("Cached diagnostic unavailable", app=url_package, error=str(exc))

    try:
        diagnostic = await generate_app_diagnostic_live(url_package)
        return {"diagnostic": diagnostic}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Diagnostic generation unavailable: {e}")
