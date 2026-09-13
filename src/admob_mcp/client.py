"""Google AdMob API v1 client."""

from __future__ import annotations

import functools
import json
import os
import random
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import structlog
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from admob_mcp.models import (
    AdMobAccount,
    AdMobApp,
    AdUnit,
    EarningsSummary,
    MediationReport,
    NetworkReport,
    ReportRow,
)

logger = structlog.get_logger(__name__)

MAX_RETRIES = 3
INITIAL_BACKOFF = 1.0
MAX_BACKOFF = 32.0

SCOPES = [
    "https://www.googleapis.com/auth/admob.report",
    "https://www.googleapis.com/auth/admob.readonly",
]


class AdMobClientError(Exception):
    """Base exception for AdMob client errors."""


def retry_with_backoff(func):  # type: ignore[no-untyped-def]
    """Decorator to retry API calls with exponential backoff."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):  # type: ignore[no-untyped-def]
        retries = 0
        backoff = INITIAL_BACKOFF
        while retries < MAX_RETRIES:
            try:
                return func(*args, **kwargs)
            except HttpError as e:
                if e.resp.status in (429, 500, 503):
                    retries += 1
                    if retries >= MAX_RETRIES:
                        raise
                    sleep_time = backoff * (0.5 + random.random())  # noqa: S311
                    logger.warning("API error, retrying", status=e.resp.status, retry=retries)
                    time.sleep(sleep_time)
                    backoff = min(backoff * 2, MAX_BACKOFF)
                else:
                    raise

    return wrapper


class AdMobClient:
    """Client for Google AdMob API v1."""

    def __init__(
        self,
        account_id: str | None = None,
        credentials_path: str | None = None,
        credentials_json: str | dict[str, Any] | None = None,
        token_path: str | None = None,
    ) -> None:
        """Initialize the AdMob client.

        Args:
            account_id: AdMob account/publisher ID (pub-XXXXXXXXXXXXXXXX).
                       Defaults to ADMOB_ACCOUNT_ID env var.
            credentials_path: Path to service account or OAuth JSON.
                            Defaults to GOOGLE_APPLICATION_CREDENTIALS env var.
            credentials_json: JSON credentials.
                            Defaults to ADMOB_CREDENTIALS env var.
            token_path: Path to user credentials/refresh token JSON.
                       Defaults to ADMOB_TOKEN_PATH or TOKEN_PATH env var, or 'token.json'.
        """
        self._account_id = account_id or os.environ.get("ADMOB_ACCOUNT_ID")
        self._credentials_path = credentials_path or os.environ.get(
            "GOOGLE_APPLICATION_CREDENTIALS"
        )
        self._credentials_json = credentials_json or os.environ.get("ADMOB_CREDENTIALS")
        self._token_path = (
            token_path or os.environ.get("ADMOB_TOKEN_PATH") or os.environ.get("TOKEN_PATH")
        )
        if not self._token_path and Path("token.json").exists():
            self._token_path = "token.json"  # noqa: S105

        self._service: Any = None
        self._logger = logger.bind(component="AdMobClient")

    def _get_service(self) -> Any:
        """Get or create the AdMob API service."""
        if self._service is not None:
            return self._service

        self._logger.info("Initializing AdMob API client")

        credentials = None

        # Try user credentials (token.json) first
        if self._token_path:
            token_file = Path(self._token_path)
            if token_file.exists():
                try:
                    self._logger.info(
                        "Loading AdMob OAuth2 credentials from token file", path=str(token_file)
                    )
                    credentials = Credentials.from_authorized_user_file(
                        str(token_file), scopes=SCOPES
                    )
                    if credentials.expired and credentials.refresh_token:
                        self._logger.info("AdMob token expired, refreshing...")
                        credentials.refresh(Request())
                except Exception as e:
                    self._logger.warning(
                        "Failed to load user credentials from token file, will fallback",
                        error=str(e),
                    )

        if not credentials and self._credentials_json:
            if isinstance(self._credentials_json, str):
                if self._credentials_json.strip().startswith("{"):
                    creds_info = json.loads(self._credentials_json)
                    credentials = service_account.Credentials.from_service_account_info(
                        creds_info, scopes=SCOPES
                    )
                elif Path(self._credentials_json).exists():
                    credentials = service_account.Credentials.from_service_account_file(
                        self._credentials_json, scopes=SCOPES
                    )
            elif isinstance(self._credentials_json, dict):
                credentials = service_account.Credentials.from_service_account_info(
                    self._credentials_json, scopes=SCOPES
                )

        if not credentials and self._credentials_path:
            creds_path = Path(self._credentials_path)
            if creds_path.exists():
                credentials = service_account.Credentials.from_service_account_file(
                    str(creds_path), scopes=SCOPES
                )

        if not credentials:
            raise AdMobClientError(
                "No valid credentials found. "
                "Set GOOGLE_APPLICATION_CREDENTIALS, ADMOB_CREDENTIALS, or ADMOB_TOKEN_PATH."
            )

        self._service = build("admob", "v1", credentials=credentials, cache_discovery=False)
        self._logger.info("AdMob client initialized successfully")
        return self._service

    @property
    def _account_path(self) -> str:
        """Get the AdMob account resource path."""
        if not self._account_id:
            raise AdMobClientError("No AdMob account ID. Set ADMOB_ACCOUNT_ID.")
        return f"accounts/{self._account_id}"

    # =========================================================================
    # Account Management
    # =========================================================================

    @retry_with_backoff
    def list_accounts(self) -> list[AdMobAccount]:
        """List all AdMob accounts.

        Returns:
            List of AdMob accounts.
        """
        self._logger.info("Listing AdMob accounts")
        service = self._get_service()

        result = service.accounts().list(pageSize=100).execute()
        accounts: list[AdMobAccount] = []

        for acct in result.get("account", []):
            accounts.append(
                AdMobAccount(
                    account_id=acct.get("publisherId", ""),
                    name=acct.get("name", ""),
                    publisher_id=acct.get("publisherId"),
                    reporting_time_zone=acct.get("reportingTimeZone"),
                    currency_code=acct.get("currencyCode"),
                )
            )

        return accounts

    @retry_with_backoff
    def get_account(self) -> AdMobAccount:
        """Get AdMob account details.

        Returns:
            Account details.
        """
        self._logger.info("Fetching account details")
        service = self._get_service()

        result = service.accounts().get(name=self._account_path).execute()

        return AdMobAccount(
            account_id=result.get("publisherId", self._account_id or ""),
            name=result.get("name"),
            publisher_id=result.get("publisherId"),
            reporting_time_zone=result.get("reportingTimeZone"),
            currency_code=result.get("currencyCode"),
        )

    # =========================================================================
    # Ad Units
    # =========================================================================

    @retry_with_backoff
    def list_ad_units(self) -> list[AdUnit]:
        """List all ad units for the account.

        Returns:
            List of ad units.
        """
        self._logger.info("Listing ad units")
        service = self._get_service()

        result = (
            service.accounts().adUnits().list(parent=self._account_path, pageSize=100).execute()
        )

        units: list[AdUnit] = []
        for unit in result.get("adUnits", []):
            units.append(
                AdUnit(
                    ad_unit_id=unit.get("adUnitId", ""),
                    name=unit.get("displayName") or unit.get("name"),
                    app_id=unit.get("appId"),
                    ad_format=unit.get("adFormat"),
                    ad_types=unit.get("adTypes", []),
                )
            )

        return units

    @retry_with_backoff
    def get_ad_unit(self, ad_unit_id: str) -> AdUnit:
        """Get specific ad unit details.

        Args:
            ad_unit_id: Ad unit ID.

        Returns:
            Ad unit details.
        """
        self._logger.info("Fetching ad unit", ad_unit_id=ad_unit_id)

        # List all and filter — AdMob API doesn't have a direct get-by-id
        units = cast("list[AdUnit]", self.list_ad_units())
        for unit in units:
            if unit.ad_unit_id == ad_unit_id:
                return unit

        raise AdMobClientError(f"Ad unit not found: {ad_unit_id}")

    # =========================================================================
    # Apps
    # =========================================================================

    @retry_with_backoff
    def list_apps(self) -> list[AdMobApp]:
        """List apps linked to the AdMob account.

        Returns:
            List of apps.
        """
        self._logger.info("Listing apps")
        service = self._get_service()

        result = service.accounts().apps().list(parent=self._account_path, pageSize=100).execute()

        apps: list[AdMobApp] = []
        for app in result.get("apps", []):
            apps.append(
                AdMobApp(
                    app_id=app.get("appId", ""),
                    name=app.get("name") or app.get("linkedAppInfo", {}).get("displayName"),
                    platform=app.get("platform"),
                    linked_app_store_id=app.get("linkedAppInfo", {}).get("appStoreId"),
                    app_approval_state=app.get("appApprovalState"),
                )
            )

        return apps

    # =========================================================================
    # Reports
    # =========================================================================

    @retry_with_backoff
    def get_network_report(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        dimensions: list[str] | None = None,
        metrics: list[str] | None = None,
        dimension_filters: list[dict[str, Any]] | None = None,
    ) -> NetworkReport:
        """Generate a network-level ad revenue report.

        Args:
            start_date: Start date (YYYY-MM-DD). Defaults to 30 days ago.
            end_date: End date (YYYY-MM-DD). Defaults to today.
            dimensions: Dimensions (default: ['DATE']). Options: DATE, MONTH,
                       WEEK, AD_UNIT, APP, AD_TYPE, COUNTRY, FORMAT, PLATFORM.
            metrics: Metrics (default: ['ESTIMATED_EARNINGS', 'IMPRESSIONS',
                    'CLICKS', 'AD_REQUESTS', 'MATCHED_REQUESTS']).
            dimension_filters: Dimension filters to apply.

        Returns:
            Network report with rows and totals.
        """
        self._logger.info("Generating network report")
        service = self._get_service()

        now = datetime.now(tz=UTC)
        if not start_date:
            start_dt = now - timedelta(days=30)
        else:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=UTC)

        if not end_date:
            end_dt = now
        else:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=UTC)

        if not dimensions:
            dimensions = ["DATE"]
        if not metrics:
            metrics = [
                "ESTIMATED_EARNINGS",
                "IMPRESSIONS",
                "CLICKS",
                "AD_REQUESTS",
                "MATCHED_REQUESTS",
            ]

        report_spec: dict[str, Any] = {
            "dateRange": {
                "startDate": {
                    "year": start_dt.year,
                    "month": start_dt.month,
                    "day": start_dt.day,
                },
                "endDate": {
                    "year": end_dt.year,
                    "month": end_dt.month,
                    "day": end_dt.day,
                },
            },
            "dimensions": dimensions,
            "metrics": metrics,
        }

        if dimension_filters:
            report_spec["dimensionFilters"] = dimension_filters

        result = (
            service.accounts()
            .networkReport()
            .generate(parent=self._account_path, body={"reportSpec": report_spec})
            .execute()
        )

        rows: list[ReportRow] = []
        totals: dict[str, Any] = {}

        for entry in result:
            if "row" in entry:
                row_data = entry["row"]
                dim_values = {}
                for key, val in row_data.get("dimensionValues", {}).items():
                    dim_values[key] = val.get("value", str(val.get("intValue", "")))

                met_values = {}
                for key, val in row_data.get("metricValues", {}).items():
                    if "microsValue" in val:
                        met_values[key] = int(val["microsValue"]) / 1_000_000
                    elif "integerValue" in val:
                        met_values[key] = int(val["integerValue"])
                    elif "doubleValue" in val:
                        met_values[key] = float(val["doubleValue"])

                rows.append(ReportRow(dimensions=dim_values, metrics=met_values))

            elif "footer" in entry:
                footer = entry["footer"]
                matching = footer.get("matchingRowCount")
                if isinstance(matching, dict):
                    for key, val in matching.items():
                        totals[key] = val
                elif matching is not None:
                    totals["matchingRowCount"] = matching

        start_str = start_date or start_dt.strftime("%Y-%m-%d")
        end_str = end_date or end_dt.strftime("%Y-%m-%d")

        return NetworkReport(
            account_id=self._account_id or "",
            date_range=f"{start_str} to {end_str}",
            rows=rows,
            totals=totals if totals else None,
        )

    @retry_with_backoff
    def get_mediation_report(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        dimensions: list[str] | None = None,
        metrics: list[str] | None = None,
    ) -> MediationReport:
        """Generate a mediation ad revenue report.

        Args:
            start_date: Start date (YYYY-MM-DD). Defaults to 30 days ago.
            end_date: End date (YYYY-MM-DD). Defaults to today.
            dimensions: Dimensions (default: ['DATE']).
            metrics: Metrics (default: ['ESTIMATED_EARNINGS', 'IMPRESSIONS', 'MATCHED_REQUESTS']).

        Returns:
            Mediation report with rows and totals.
        """
        self._logger.info("Generating mediation report")
        service = self._get_service()

        now = datetime.now(tz=UTC)
        if not start_date:
            start_dt = now - timedelta(days=30)
        else:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=UTC)

        if not end_date:
            end_dt = now
        else:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=UTC)

        if not dimensions:
            dimensions = ["DATE"]
        if not metrics:
            metrics = ["ESTIMATED_EARNINGS", "IMPRESSIONS", "MATCHED_REQUESTS"]

        report_spec = {
            "dateRange": {
                "startDate": {
                    "year": start_dt.year,
                    "month": start_dt.month,
                    "day": start_dt.day,
                },
                "endDate": {
                    "year": end_dt.year,
                    "month": end_dt.month,
                    "day": end_dt.day,
                },
            },
            "dimensions": dimensions,
            "metrics": metrics,
        }

        result = (
            service.accounts()
            .mediationReport()
            .generate(parent=self._account_path, body={"reportSpec": report_spec})
            .execute()
        )

        rows: list[ReportRow] = []
        for entry in result:
            if "row" in entry:
                row_data = entry["row"]
                dim_values = {}
                for key, val in row_data.get("dimensionValues", {}).items():
                    dim_values[key] = val.get("value", "")

                met_values = {}
                for key, val in row_data.get("metricValues", {}).items():
                    if "microsValue" in val:
                        met_values[key] = int(val["microsValue"]) / 1_000_000
                    elif "integerValue" in val:
                        met_values[key] = int(val["integerValue"])
                    elif "doubleValue" in val:
                        met_values[key] = float(val["doubleValue"])

                rows.append(ReportRow(dimensions=dim_values, metrics=met_values))

        start_str = start_date or start_dt.strftime("%Y-%m-%d")
        end_str = end_date or end_dt.strftime("%Y-%m-%d")

        return MediationReport(
            account_id=self._account_id or "",
            date_range=f"{start_str} to {end_str}",
            rows=rows,
        )

    @retry_with_backoff
    def get_earnings_summary(self, app_id: str | None = None) -> EarningsSummary:
        """Get summarized earnings across time periods.

        Args:
            app_id: Optional AdMob app ID to filter the report.

        Returns:
            Earnings summary with today, yesterday, 7-day, 30-day, and monthly totals.
        """
        self._logger.info("Fetching earnings summary", app_id=app_id)

        now = datetime.now(tz=UTC)

        dimension_filters = None
        if app_id:
            dimension_filters = [{"dimension": "APP", "matchesAny": {"values": [app_id]}}]

        # Today
        today_report = self.get_network_report(
            start_date=now.strftime("%Y-%m-%d"),
            end_date=now.strftime("%Y-%m-%d"),
            dimensions=["DATE"],
            metrics=["ESTIMATED_EARNINGS", "IMPRESSIONS", "CLICKS"],
            dimension_filters=dimension_filters,
        )

        today_earnings = 0.0
        today_impressions = 0
        today_clicks = 0
        for row in today_report.rows:
            today_earnings += row.metrics.get("ESTIMATED_EARNINGS", 0)
            today_impressions += int(row.metrics.get("IMPRESSIONS", 0))
            today_clicks += int(row.metrics.get("CLICKS", 0))

        # Yesterday
        yesterday = now - timedelta(days=1)
        yesterday_report = self.get_network_report(
            start_date=yesterday.strftime("%Y-%m-%d"),
            end_date=yesterday.strftime("%Y-%m-%d"),
            dimensions=["DATE"],
            metrics=["ESTIMATED_EARNINGS"],
            dimension_filters=dimension_filters,
        )
        yesterday_earnings = sum(
            row.metrics.get("ESTIMATED_EARNINGS", 0) for row in yesterday_report.rows
        )

        # Last 7 days
        week_ago = now - timedelta(days=7)
        week_report = self.get_network_report(
            start_date=week_ago.strftime("%Y-%m-%d"),
            end_date=now.strftime("%Y-%m-%d"),
            dimensions=["DATE"],
            metrics=["ESTIMATED_EARNINGS"],
            dimension_filters=dimension_filters,
        )
        week_earnings = sum(row.metrics.get("ESTIMATED_EARNINGS", 0) for row in week_report.rows)

        # Last 30 days
        month_ago = now - timedelta(days=30)
        month_report = self.get_network_report(
            start_date=month_ago.strftime("%Y-%m-%d"),
            end_date=now.strftime("%Y-%m-%d"),
            dimensions=["DATE"],
            metrics=["ESTIMATED_EARNINGS"],
            dimension_filters=dimension_filters,
        )
        month_earnings = sum(row.metrics.get("ESTIMATED_EARNINGS", 0) for row in month_report.rows)

        ecpm = (today_earnings / today_impressions * 1000) if today_impressions > 0 else 0

        return EarningsSummary(
            account_id=self._account_id or "",
            today=round(today_earnings, 2),
            yesterday=round(yesterday_earnings, 2),
            last_7_days=round(week_earnings, 2),
            last_30_days=round(month_earnings, 2),
            this_month=round(month_earnings, 2),
            impressions_today=today_impressions,
            clicks_today=today_clicks,
            ecpm_today=round(ecpm, 2),
        )
