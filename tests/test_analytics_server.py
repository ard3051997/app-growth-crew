"""Tests for analytics_mcp/server.py."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from analytics_mcp.client import AnalyticsClient, AnalyticsClientError
from analytics_mcp.models import (
    AcquisitionReport,
    ActiveUsersReport,
    AnalyticsReport,
    DemographicsReport,
    EventReport,
    RealtimeReport,
    RevenueReport,
    ScreenViewReport,
)
from analytics_mcp.server import (
    get_active_users,
    get_crash_events,
    get_events,
    get_realtime_report,
    get_revenue_report,
    get_screen_views,
    get_user_acquisition,
    get_user_demographics,
    mcp,
    run_report,
)


def _mock_context(client: MagicMock) -> MagicMock:
    """Create a mock MCP context with the given client."""
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {"client": client}
    return ctx


@pytest.fixture
def mock_client() -> MagicMock:
    """Create a mock AnalyticsClient."""
    return MagicMock(spec=AnalyticsClient)


@pytest.fixture(autouse=True)
def _patch_mcp_context(mock_client: MagicMock) -> Any:
    """Patch mcp.get_context to return our mock client."""
    ctx = _mock_context(mock_client)
    with patch.object(mcp, "get_context", return_value=ctx):
        yield


class TestLifespan:
    """Test Analytics server lifespan."""

    @pytest.mark.asyncio
    async def test_lifespan_success(self) -> None:
        """Test successful lifespan initialization."""
        from analytics_mcp.server import lifespan

        mock_server = MagicMock()

        with (
            patch("analytics_mcp.server.AnalyticsClient") as MockClient,
            patch("analytics_mcp.server.AnalyticsClientError", AnalyticsClientError),
        ):
            instance = MockClient.return_value
            async with lifespan(mock_server) as ctx:
                assert ctx["client"] is instance

    @pytest.mark.asyncio
    async def test_lifespan_failure(self) -> None:
        """Test lifespan initialization failure."""
        from analytics_mcp.server import lifespan

        mock_server = MagicMock()

        with (
            patch(
                "analytics_mcp.server.AnalyticsClient",
                side_effect=AnalyticsClientError("bad property ID"),
            ),
            patch("analytics_mcp.server.AnalyticsClientError", AnalyticsClientError),
        ):
            async with lifespan(mock_server) as ctx:
                assert ctx["client"] is None


class TestReportTools:
    """Test report server tools."""

    def test_run_report(self, mock_client: MagicMock) -> None:
        mock_client.run_report.return_value = AnalyticsReport(
            property_id="123",
            report_name="custom_report",
            date_range="30daysAgo to today",
            rows=[],
        )

        result = run_report(
            dimensions=["date"],
            metrics=["activeUsers"],
            start_date="30daysAgo",
            end_date="today",
            limit=50,
            order_by_metric="activeUsers",
        )
        mock_client.run_report.assert_called_once_with(
            dimensions=["date"],
            metrics=["activeUsers"],
            start_date="30daysAgo",
            end_date="today",
            limit=50,
            order_by_metric="activeUsers",
        )
        assert result["property_id"] == "123"

    def test_get_realtime_report(self, mock_client: MagicMock) -> None:
        mock_client.get_realtime_report.return_value = RealtimeReport(
            property_id="123",
            active_users=10,
            rows=[],
        )

        result = get_realtime_report(dimensions=["screen"], metrics=["activeUsers"])
        mock_client.get_realtime_report.assert_called_once_with(
            dimensions=["screen"],
            metrics=["activeUsers"],
        )
        assert result["property_id"] == "123"

    def test_get_active_users(self, mock_client: MagicMock) -> None:
        mock_client.get_active_users.return_value = ActiveUsersReport(
            property_id="123",
            date_range="30daysAgo to today",
            daily_active_users=[],
            total_users=0,
            average_dau=0.0,
        )

        result = get_active_users(start_date="30daysAgo", end_date="today")
        mock_client.get_active_users.assert_called_once_with(
            start_date="30daysAgo", end_date="today"
        )
        assert result["property_id"] == "123"

    def test_get_user_acquisition(self, mock_client: MagicMock) -> None:
        mock_client.get_user_acquisition.return_value = AcquisitionReport(
            property_id="123",
            date_range="30daysAgo to today",
            channels=[],
            total_new_users=0,
        )

        result = get_user_acquisition(start_date="30daysAgo", end_date="today")
        mock_client.get_user_acquisition.assert_called_once_with(
            start_date="30daysAgo", end_date="today"
        )
        assert result["property_id"] == "123"

    def test_get_events(self, mock_client: MagicMock) -> None:
        mock_client.get_events.return_value = EventReport(
            property_id="123",
            date_range="7daysAgo to today",
            events=[],
            total_events=0,
        )

        result = get_events(
            start_date="7daysAgo", end_date="today", limit=10, event_name_filter="click"
        )
        mock_client.get_events.assert_called_once_with(
            start_date="7daysAgo", end_date="today", limit=10, event_name_filter="click"
        )
        assert result["property_id"] == "123"

    def test_get_revenue_report(self, mock_client: MagicMock) -> None:
        mock_client.get_revenue_report.return_value = RevenueReport(
            property_id="123",
            date_range="30daysAgo to today",
            total_revenue=0.0,
            purchase_revenue=0.0,
            ad_revenue=0.0,
            daily_revenue=[],
        )

        result = get_revenue_report(start_date="30daysAgo", end_date="today")
        mock_client.get_revenue_report.assert_called_once_with(
            start_date="30daysAgo", end_date="today"
        )
        assert result["property_id"] == "123"

    def test_get_user_demographics(self, mock_client: MagicMock) -> None:
        mock_client.get_user_demographics.return_value = DemographicsReport(
            property_id="123",
            date_range="30daysAgo to today",
            countries=[],
            devices=[],
            os_versions=[],
        )

        result = get_user_demographics(start_date="30daysAgo", end_date="today")
        mock_client.get_user_demographics.assert_called_once_with(
            start_date="30daysAgo", end_date="today"
        )
        assert result["property_id"] == "123"

    def test_get_screen_views(self, mock_client: MagicMock) -> None:
        mock_client.get_screen_views.return_value = ScreenViewReport(
            property_id="123",
            date_range="7daysAgo to today",
            screens=[],
            total_screen_views=0,
        )

        result = get_screen_views(start_date="7daysAgo", end_date="today", limit=50)
        mock_client.get_screen_views.assert_called_once_with(
            start_date="7daysAgo", end_date="today", limit=50
        )
        assert result["property_id"] == "123"

    def test_get_crash_events(self, mock_client: MagicMock) -> None:
        mock_client.get_crash_events.return_value = EventReport(
            property_id="123",
            date_range="7daysAgo to today",
            events=[],
            total_events=0,
        )

        result = get_crash_events(start_date="7daysAgo", end_date="today")
        mock_client.get_crash_events.assert_called_once_with(
            start_date="7daysAgo", end_date="today"
        )
        assert result["property_id"] == "123"


class TestServerMain:
    """Test server main entry point."""

    def test_main_calls_mcp_run(self) -> None:
        from analytics_mcp.server import main

        with patch.object(mcp, "run") as mock_run:
            main([])
            mock_run.assert_called_once()
