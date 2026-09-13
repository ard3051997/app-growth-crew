"""Google Analytics 4 Data API client."""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
from typing import Any

import structlog
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Filter,
    FilterExpression,
    Metric,
    OrderBy,
    RunRealtimeReportRequest,
    RunReportRequest,
)
from google.api_core import exceptions as google_exceptions
from google.oauth2 import service_account

from analytics_mcp.models import (
    AcquisitionReport,
    ActiveUsersReport,
    AnalyticsReport,
    DemographicsReport,
    DimensionValue,
    EventReport,
    MetricValue,
    RealtimeReport,
    ReportRow,
    RetentionReport,
    RevenueReport,
    ScreenViewReport,
)
from mcp_gc_shared.retry import retry_on_transient

logger = structlog.get_logger(__name__)

SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]

retry_with_backoff = retry_on_transient(
    google_exceptions.TooManyRequests,
    google_exceptions.ServiceUnavailable,
    google_exceptions.InternalServerError,
)


class AnalyticsClientError(Exception):
    """Base exception for Analytics client errors."""


class AnalyticsClient:
    """Client for Google Analytics 4 Data API."""

    def __init__(
        self,
        property_id: str | None = None,
        credentials_path: str | None = None,
        credentials_json: str | dict[str, Any] | None = None,
    ) -> None:
        """Initialize the Analytics client.

        Args:
            property_id: GA4 property ID (e.g., '123456789').
                        Defaults to GA4_PROPERTY_ID env var.
            credentials_path: Path to service account JSON.
                            Defaults to GOOGLE_APPLICATION_CREDENTIALS env var.
            credentials_json: JSON credentials string or dict.
                            Defaults to GA4_CREDENTIALS env var.
        """
        self._property_id = property_id or os.environ.get("GA4_PROPERTY_ID")
        self._credentials_path = credentials_path or os.environ.get(
            "GOOGLE_APPLICATION_CREDENTIALS"
        )
        self._credentials_json = credentials_json or os.environ.get("GA4_CREDENTIALS")
        self._client: BetaAnalyticsDataClient | None = None
        self._logger = logger.bind(component="AnalyticsClient")

        if not self._property_id:
            raise AnalyticsClientError(
                "No GA4 property ID found. Set GA4_PROPERTY_ID environment variable."
            )

    def _get_client(self) -> BetaAnalyticsDataClient:
        """Get or create the Analytics Data API client."""
        if self._client is not None:
            return self._client

        self._logger.info("Initializing GA4 Data API client")

        credentials = None

        # Try credentials JSON first
        if self._credentials_json:
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

        # Fall back to file path
        if not credentials and self._credentials_path:
            creds_path = Path(self._credentials_path)
            if creds_path.exists():
                credentials = service_account.Credentials.from_service_account_file(
                    str(creds_path), scopes=SCOPES
                )

        if credentials:
            self._client = BetaAnalyticsDataClient(credentials=credentials)
        else:
            # Try default credentials (ADC)
            self._client = BetaAnalyticsDataClient()

        self._logger.info("GA4 client initialized successfully")
        return self._client

    @property
    def _property_path(self) -> str:
        """Get the GA4 property resource path."""
        return f"properties/{self._property_id}"

    def _parse_report_rows(self, response: Any) -> list[ReportRow]:
        """Parse GA4 report response rows into ReportRow models."""
        rows: list[ReportRow] = []
        dim_headers = [h.name for h in response.dimension_headers]
        met_headers = [h.name for h in response.metric_headers]

        for row in response.rows:
            dimensions = [
                DimensionValue(name=dim_headers[i], value=val.value)
                for i, val in enumerate(row.dimension_values)
            ]
            metrics = [
                MetricValue(name=met_headers[i], value=val.value)
                for i, val in enumerate(row.metric_values)
            ]
            rows.append(ReportRow(dimensions=dimensions, metrics=metrics))

        return rows

    # =========================================================================
    # Core Report
    # =========================================================================

    @retry_with_backoff
    def run_report(
        self,
        dimensions: list[str],
        metrics: list[str],
        start_date: str = "30daysAgo",
        end_date: str = "today",
        limit: int = 100,
        dimension_filter: dict[str, str] | None = None,
        order_by_metric: str | None = None,
    ) -> AnalyticsReport:
        """Run a custom GA4 report.

        Args:
            dimensions: List of dimension names (e.g., ['date', 'country']).
            metrics: List of metric names (e.g., ['activeUsers', 'sessions']).
            start_date: Start date (YYYY-MM-DD or relative like '30daysAgo').
            end_date: End date (YYYY-MM-DD or 'today').
            limit: Max rows to return.
            dimension_filter: Optional filter {dimension_name: value}.
            order_by_metric: Optional metric name to sort by (descending).

        Returns:
            Analytics report with rows.
        """
        self._logger.info("Running report", dimensions=dimensions, metrics=metrics)
        client = self._get_client()

        request = RunReportRequest(
            property=self._property_path,
            dimensions=[Dimension(name=d) for d in dimensions],
            metrics=[Metric(name=m) for m in metrics],
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            limit=limit,
        )

        if dimension_filter:
            for dim_name, dim_value in dimension_filter.items():
                request.dimension_filter = FilterExpression(
                    filter=Filter(
                        field_name=dim_name,
                        string_filter=Filter.StringFilter(value=dim_value),
                    )
                )

        if order_by_metric:
            request.order_bys = [
                OrderBy(
                    metric=OrderBy.MetricOrderBy(metric_name=order_by_metric),
                    desc=True,
                )
            ]

        response = client.run_report(request)
        rows = self._parse_report_rows(response)

        return AnalyticsReport(
            property_id=self._property_id or "",
            report_name="custom_report",
            date_range=f"{start_date} to {end_date}",
            row_count=response.row_count,
            rows=rows,
        )

    @retry_with_backoff
    def get_realtime_report(
        self,
        dimensions: list[str] | None = None,
        metrics: list[str] | None = None,
    ) -> RealtimeReport:
        """Get real-time analytics data.

        Args:
            dimensions: Dimensions (default: ['unifiedScreenName']).
            metrics: Metrics (default: ['activeUsers']).

        Returns:
            Realtime report with active users.
        """
        self._logger.info("Fetching realtime report")
        client = self._get_client()

        if not dimensions:
            dimensions = ["unifiedScreenName"]
        if not metrics:
            metrics = ["activeUsers"]

        request = RunRealtimeReportRequest(
            property=self._property_path,
            dimensions=[Dimension(name=d) for d in dimensions],
            metrics=[Metric(name=m) for m in metrics],
        )

        response = client.run_realtime_report(request)
        rows = self._parse_report_rows(response)

        active_users = 0
        for row in response.rows:
            for val in row.metric_values:
                with contextlib.suppress(ValueError):
                    active_users += int(val.value)

        return RealtimeReport(
            property_id=self._property_id or "",
            active_users=active_users,
            rows=rows,
        )

    # =========================================================================
    # Pre-built Reports
    # =========================================================================

    @retry_with_backoff
    def get_active_users(
        self,
        start_date: str = "30daysAgo",
        end_date: str = "today",
        dimension_filter: dict[str, str] | None = None,
    ) -> ActiveUsersReport:
        """Get daily active users over a date range.

        Args:
            start_date: Start date.
            end_date: End date.
            dimension_filter: Optional dimension filter.

        Returns:
            Active users report with DAU breakdown.
        """
        self._logger.info("Fetching active users", start=start_date, end=end_date)

        report = self.run_report(
            dimensions=["date"],
            metrics=["activeUsers"],
            start_date=start_date,
            end_date=end_date,
            limit=366,
            dimension_filter=dimension_filter,
        )

        daily = []
        total = 0
        for row in report.rows:
            date_val = row.dimensions[0].value if row.dimensions else ""
            users = int(row.metrics[0].value) if row.metrics else 0
            daily.append({"date": date_val, "active_users": users})
            total += users

        avg_dau = total / len(daily) if daily else 0

        return ActiveUsersReport(
            property_id=self._property_id or "",
            date_range=f"{start_date} to {end_date}",
            daily_active_users=daily,
            total_users=total,
            average_dau=round(avg_dau, 1),
        )

    @retry_with_backoff
    def get_user_acquisition(
        self,
        start_date: str = "30daysAgo",
        end_date: str = "today",
    ) -> AcquisitionReport:
        """Get user acquisition by source/medium.

        Args:
            start_date: Start date.
            end_date: End date.

        Returns:
            Acquisition report by channel.
        """
        self._logger.info("Fetching acquisition data")

        report = self.run_report(
            dimensions=["sessionDefaultChannelGroup"],
            metrics=["newUsers", "sessions", "engagementRate"],
            start_date=start_date,
            end_date=end_date,
            order_by_metric="newUsers",
        )

        channels = []
        total_new = 0
        for row in report.rows:
            channel = row.dimensions[0].value if row.dimensions else "unknown"
            new_users = int(row.metrics[0].value) if len(row.metrics) > 0 else 0
            sessions = int(row.metrics[1].value) if len(row.metrics) > 1 else 0
            engagement = float(row.metrics[2].value) if len(row.metrics) > 2 else 0.0
            channels.append(
                {
                    "channel": channel,
                    "new_users": new_users,
                    "sessions": sessions,
                    "engagement_rate": round(engagement, 4),
                }
            )
            total_new += new_users

        return AcquisitionReport(
            property_id=self._property_id or "",
            date_range=f"{start_date} to {end_date}",
            channels=channels,
            total_new_users=total_new,
        )

    @retry_with_backoff
    def get_retention(
        self,
        start_date: str = "30daysAgo",
        end_date: str = "today",
        dimension_filter: dict[str, str] | None = None,
    ) -> RetentionReport:
        """Get cohort retention data.

        Args:
            start_date: Start date.
            end_date: End date.
            dimension_filter: Optional dimension filter.

        Returns:
            Retention report with cohort data.
        """
        self._logger.info("Fetching retention data")

        # Use day-over-day retention via new vs returning users
        report = self.run_report(
            dimensions=["date", "newVsReturning"],
            metrics=["activeUsers"],
            start_date=start_date,
            end_date=end_date,
            limit=366,
            dimension_filter=dimension_filter,
        )

        cohorts: list[dict[str, Any]] = []
        date_data: dict[str, dict[str, int]] = {}

        for row in report.rows:
            date_val = row.dimensions[0].value if len(row.dimensions) > 0 else ""
            user_type = row.dimensions[1].value if len(row.dimensions) > 1 else ""
            users = int(row.metrics[0].value) if row.metrics else 0

            if date_val not in date_data:
                date_data[date_val] = {"new": 0, "returning": 0}
            if user_type == "new":
                date_data[date_val]["new"] = users
            else:
                date_data[date_val]["returning"] = users

        for date_val, data in sorted(date_data.items()):
            total = data["new"] + data["returning"]
            retention_rate = data["returning"] / total if total > 0 else 0
            cohorts.append(
                {
                    "date": date_val,
                    "new_users": data["new"],
                    "returning_users": data["returning"],
                    "total_users": total,
                    "retention_rate": round(retention_rate, 4),
                }
            )

        return RetentionReport(
            property_id=self._property_id or "",
            date_range=f"{start_date} to {end_date}",
            cohorts=cohorts,
        )

    @retry_with_backoff
    def get_events(
        self,
        start_date: str = "7daysAgo",
        end_date: str = "today",
        limit: int = 500,
        event_name_filter: str | None = None,
        dimension_filter: dict[str, str] | None = None,
    ) -> EventReport:
        """Get top events by count.

        Args:
            start_date: Start date.
            end_date: End date.
            limit: Max events to return.
            event_name_filter: Optional filter by event name.
            dimension_filter: Optional dimension filter.

        Returns:
            Event report with top events.
        """
        self._logger.info("Fetching events data")

        dim_filter = dimension_filter or {}
        if event_name_filter:
            dim_filter["eventName"] = event_name_filter

        report = self.run_report(
            dimensions=["eventName"],
            metrics=["eventCount", "totalUsers"],
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            dimension_filter=dim_filter,
            order_by_metric="eventCount",
        )

        events = []
        total = 0
        for row in report.rows:
            event_name = row.dimensions[0].value if row.dimensions else ""
            count = int(row.metrics[0].value) if len(row.metrics) > 0 else 0
            users = int(row.metrics[1].value) if len(row.metrics) > 1 else 0
            events.append(
                {
                    "event_name": event_name,
                    "event_count": count,
                    "total_users": users,
                }
            )
            total += count

        return EventReport(
            property_id=self._property_id or "",
            date_range=f"{start_date} to {end_date}",
            events=events,
            total_events=total,
        )

    @retry_with_backoff
    def get_revenue_report(
        self,
        start_date: str = "30daysAgo",
        end_date: str = "today",
    ) -> RevenueReport:
        """Get revenue breakdown.

        Args:
            start_date: Start date.
            end_date: End date.

        Returns:
            Revenue report with daily breakdown.
        """
        self._logger.info("Fetching revenue data")

        report = self.run_report(
            dimensions=["date"],
            metrics=["totalRevenue", "purchaseRevenue"],
            start_date=start_date,
            end_date=end_date,
            limit=366,
        )

        daily = []
        total_rev = 0.0
        total_purchase = 0.0
        total_ad = 0.0

        for row in report.rows:
            date_val = row.dimensions[0].value if row.dimensions else ""
            revenue = float(row.metrics[0].value) if len(row.metrics) > 0 else 0.0
            purchase = float(row.metrics[1].value) if len(row.metrics) > 1 else 0.0
            ad_rev = max(0.0, revenue - purchase)
            daily.append(
                {
                    "date": date_val,
                    "total_revenue": round(revenue, 2),
                    "purchase_revenue": round(purchase, 2),
                    "ad_revenue": round(ad_rev, 2),
                }
            )
            total_rev += revenue
            total_purchase += purchase
            total_ad += ad_rev

        return RevenueReport(
            property_id=self._property_id or "",
            date_range=f"{start_date} to {end_date}",
            total_revenue=round(total_rev, 2),
            purchase_revenue=round(total_purchase, 2),
            ad_revenue=round(total_ad, 2),
            daily_revenue=daily,
        )

    @retry_with_backoff
    def get_user_demographics(
        self,
        start_date: str = "30daysAgo",
        end_date: str = "today",
    ) -> DemographicsReport:
        """Get user demographics (country, device, OS).

        Args:
            start_date: Start date.
            end_date: End date.

        Returns:
            Demographics report with country, device, and OS breakdowns.
        """
        self._logger.info("Fetching demographics")

        # Countries
        country_report = self.run_report(
            dimensions=["country"],
            metrics=["activeUsers"],
            start_date=start_date,
            end_date=end_date,
            order_by_metric="activeUsers",
            limit=20,
        )
        countries = [
            {
                "country": row.dimensions[0].value if row.dimensions else "",
                "users": int(row.metrics[0].value) if row.metrics else 0,
            }
            for row in country_report.rows
        ]

        # Device categories
        device_report = self.run_report(
            dimensions=["deviceCategory"],
            metrics=["activeUsers"],
            start_date=start_date,
            end_date=end_date,
            order_by_metric="activeUsers",
        )
        devices = [
            {
                "device": row.dimensions[0].value if row.dimensions else "",
                "users": int(row.metrics[0].value) if row.metrics else 0,
            }
            for row in device_report.rows
        ]

        # OS versions
        os_report = self.run_report(
            dimensions=["operatingSystemVersion"],
            metrics=["activeUsers"],
            start_date=start_date,
            end_date=end_date,
            order_by_metric="activeUsers",
            limit=15,
        )
        os_versions = [
            {
                "os_version": row.dimensions[0].value if row.dimensions else "",
                "users": int(row.metrics[0].value) if row.metrics else 0,
            }
            for row in os_report.rows
        ]

        return DemographicsReport(
            property_id=self._property_id or "",
            date_range=f"{start_date} to {end_date}",
            countries=countries,
            devices=devices,
            os_versions=os_versions,
        )

    @retry_with_backoff
    def get_screen_views(
        self,
        start_date: str = "7daysAgo",
        end_date: str = "today",
        limit: int = 30,
    ) -> ScreenViewReport:
        """Get top screens by views.

        Args:
            start_date: Start date.
            end_date: End date.
            limit: Max screens to return.

        Returns:
            Screen view report.
        """
        self._logger.info("Fetching screen views")

        report = self.run_report(
            dimensions=["unifiedScreenName"],
            metrics=["screenPageViews", "activeUsers"],
            start_date=start_date,
            end_date=end_date,
            order_by_metric="screenPageViews",
            limit=limit,
        )

        screens = []
        total = 0
        for row in report.rows:
            screen = row.dimensions[0].value if row.dimensions else ""
            views = int(row.metrics[0].value) if len(row.metrics) > 0 else 0
            users = int(row.metrics[1].value) if len(row.metrics) > 1 else 0
            screens.append(
                {
                    "screen_name": screen,
                    "screen_views": views,
                    "active_users": users,
                }
            )
            total += views

        return ScreenViewReport(
            property_id=self._property_id or "",
            date_range=f"{start_date} to {end_date}",
            screens=screens,
            total_screen_views=total,
        )

    @retry_with_backoff
    def get_crash_events(
        self,
        start_date: str = "7daysAgo",
        end_date: str = "today",
    ) -> EventReport:
        """Get app crash events from Analytics.

        Args:
            start_date: Start date.
            end_date: End date.

        Returns:
            Crash events report.
        """
        self._logger.info("Fetching crash events")

        return self.get_events(
            start_date=start_date,
            end_date=end_date,
            event_name_filter="app_exception",
        )
