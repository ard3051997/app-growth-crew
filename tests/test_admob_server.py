"""Tests for admob_mcp/server.py."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from admob_mcp.client import AdMobClient, AdMobClientError
from admob_mcp.models import (
    AdMobAccount,
    AdMobApp,
    AdUnit,
    EarningsSummary,
    MediationReport,
    NetworkReport,
)
from admob_mcp.server import (
    get_account,
    get_ad_unit,
    get_earnings_summary,
    get_mediation_report,
    get_network_report,
    list_accounts,
    list_ad_units,
    list_apps,
    mcp,
)


def _mock_context(client: MagicMock) -> MagicMock:
    """Create a mock MCP context with the given client."""
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {"client": client}
    return ctx


@pytest.fixture
def mock_client() -> MagicMock:
    """Create a mock AdMobClient."""
    return MagicMock(spec=AdMobClient)


@pytest.fixture(autouse=True)
def _patch_mcp_context(mock_client: MagicMock) -> Any:
    """Patch mcp.get_context to return our mock client."""
    ctx = _mock_context(mock_client)
    with patch.object(mcp, "get_context", return_value=ctx):
        yield


class TestLifespan:
    """Test AdMob server lifespan."""

    @pytest.mark.asyncio
    async def test_lifespan_success(self) -> None:
        """Test successful lifespan initialization."""
        from admob_mcp.server import lifespan

        mock_server = MagicMock()

        with (
            patch("admob_mcp.server.AdMobClient") as MockClient,
            patch("admob_mcp.server.AdMobClientError", AdMobClientError),
        ):
            instance = MockClient.return_value
            async with lifespan(mock_server) as ctx:
                assert ctx["client"] is instance

    @pytest.mark.asyncio
    async def test_lifespan_failure(self) -> None:
        """Test lifespan initialization failure."""
        from admob_mcp.server import lifespan

        mock_server = MagicMock()

        with (
            patch("admob_mcp.server.AdMobClient", side_effect=AdMobClientError("no credentials")),
            patch("admob_mcp.server.AdMobClientError", AdMobClientError),
        ):
            async with lifespan(mock_server) as ctx:
                # Client should not be stored in ctx if initialization fails
                assert ctx["client"] is None


class TestAccountTools:
    """Test account server tools."""

    def test_list_accounts(self, mock_client: MagicMock) -> None:
        mock_client.list_accounts.return_value = [
            AdMobAccount(account_id="pub-123", name="My Account"),
        ]

        result = list_accounts()
        mock_client.list_accounts.assert_called_once()
        assert len(result) == 1
        assert result[0]["account_id"] == "pub-123"

    def test_get_account(self, mock_client: MagicMock) -> None:
        mock_client.get_account.return_value = AdMobAccount(account_id="pub-123", name="My Account")

        result = get_account()
        mock_client.get_account.assert_called_once()
        assert result["account_id"] == "pub-123"


class TestAdUnitTools:
    """Test ad unit server tools."""

    def test_list_ad_units(self, mock_client: MagicMock) -> None:
        mock_client.list_ad_units.return_value = [
            AdUnit(ad_unit_id="unit-123", name="Banner"),
        ]

        result = list_ad_units()
        mock_client.list_ad_units.assert_called_once()
        assert len(result) == 1
        assert result[0]["ad_unit_id"] == "unit-123"

    def test_get_ad_unit(self, mock_client: MagicMock) -> None:
        mock_client.get_ad_unit.return_value = AdUnit(ad_unit_id="unit-123", name="Banner")

        result = get_ad_unit("unit-123")
        mock_client.get_ad_unit.assert_called_once_with("unit-123")
        assert result["ad_unit_id"] == "unit-123"


class TestAppTools:
    """Test app server tools."""

    def test_list_apps(self, mock_client: MagicMock) -> None:
        mock_client.list_apps.return_value = [
            AdMobApp(app_id="app-123", name="My App"),
        ]

        result = list_apps()
        mock_client.list_apps.assert_called_once()
        assert len(result) == 1
        assert result[0]["app_id"] == "app-123"


class TestReportTools:
    """Test report server tools."""

    def test_get_network_report(self, mock_client: MagicMock) -> None:
        mock_client.get_network_report.return_value = NetworkReport(
            account_id="pub-123",
            date_range="2024-01-01 to 2024-01-02",
            rows=[],
        )

        result = get_network_report(
            start_date="2024-01-01",
            end_date="2024-01-02",
            dimensions=["DATE"],
            metrics=["ESTIMATED_EARNINGS"],
        )
        mock_client.get_network_report.assert_called_once_with(
            start_date="2024-01-01",
            end_date="2024-01-02",
            dimensions=["DATE"],
            metrics=["ESTIMATED_EARNINGS"],
        )
        assert result["account_id"] == "pub-123"

    def test_get_mediation_report(self, mock_client: MagicMock) -> None:
        mock_client.get_mediation_report.return_value = MediationReport(
            account_id="pub-123",
            date_range="2024-01-01 to 2024-01-02",
            rows=[],
        )

        result = get_mediation_report(
            start_date="2024-01-01",
            end_date="2024-01-02",
            dimensions=["DATE"],
            metrics=["ESTIMATED_EARNINGS"],
        )
        mock_client.get_mediation_report.assert_called_once_with(
            start_date="2024-01-01",
            end_date="2024-01-02",
            dimensions=["DATE"],
            metrics=["ESTIMATED_EARNINGS"],
        )
        assert result["account_id"] == "pub-123"

    def test_get_earnings_summary(self, mock_client: MagicMock) -> None:
        mock_client.get_earnings_summary.return_value = EarningsSummary(
            account_id="pub-123",
            today=1.23,
            yesterday=4.56,
            last_7_days=10.0,
            last_30_days=50.0,
            this_month=50.0,
            impressions_today=100,
            clicks_today=5,
            ecpm_today=12.30,
        )

        result = get_earnings_summary()
        mock_client.get_earnings_summary.assert_called_once()
        assert result["today"] == 1.23
        assert result["ecpm_today"] == 12.30


class TestServerMain:
    """Test server main entry point."""

    def test_main_calls_mcp_run(self) -> None:
        from admob_mcp.server import main

        with patch.object(mcp, "run") as mock_run:
            main([])
            mock_run.assert_called_once()
