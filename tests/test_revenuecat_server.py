"""Tests for revenuecat_mcp/server.py."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from revenuecat_mcp.client import RevenueCatClient, RevenueCatClientError
from revenuecat_mcp.models import (
    ChartData,
    ChartDataPoint,
    EntitlementGrantResult,
    Offering,
    OverviewMetrics,
    Package,
    Product,
    RefundResult,
    Subscriber,
    Transaction,
)
from revenuecat_mcp.server import (
    get_charts,
    get_offering,
    get_overview_metrics,
    get_subscriber,
    get_transaction_history,
    grant_entitlement,
    list_offerings,
    list_products,
    mcp,
    refund_purchase,
    revoke_entitlement,
)


def _mock_context(client: MagicMock) -> MagicMock:
    """Create a mock MCP context with the given client."""
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {"client": client}
    return ctx


@pytest.fixture
def mock_client() -> MagicMock:
    """Create a mock RevenueCatClient."""
    return MagicMock(spec=RevenueCatClient)


@pytest.fixture(autouse=True)
def _patch_mcp_context(mock_client: MagicMock) -> Any:
    """Patch mcp.get_context to return our mock client."""
    ctx = _mock_context(mock_client)
    with patch.object(mcp, "get_context", return_value=ctx):
        yield


class TestLifespan:
    """Test RevenueCat server lifespan."""

    @pytest.mark.asyncio
    async def test_lifespan_success(self) -> None:
        """Test successful lifespan initialization."""
        from revenuecat_mcp.server import lifespan

        mock_server = MagicMock()

        with (
            patch("revenuecat_mcp.server.RevenueCatClient") as MockClient,
            patch("revenuecat_mcp.server.RevenueCatClientError", RevenueCatClientError),
        ):
            instance = MockClient.return_value
            async with lifespan(mock_server) as ctx:
                assert ctx["client"] is instance

    @pytest.mark.asyncio
    async def test_lifespan_failure(self) -> None:
        """Test lifespan initialization failure."""
        from revenuecat_mcp.server import lifespan

        mock_server = MagicMock()

        with (
            patch(
                "revenuecat_mcp.server.RevenueCatClient",
                side_effect=RevenueCatClientError("no key"),
            ),
            patch("revenuecat_mcp.server.RevenueCatClientError", RevenueCatClientError),
        ):
            async with lifespan(mock_server) as ctx:
                assert ctx["client"] is None


class TestSubscriberTools:
    """Test subscriber server tools."""

    def test_get_subscriber(self, mock_client: MagicMock) -> None:
        mock_client.get_subscriber.return_value = Subscriber(
            app_user_id="user123",
            entitlements={},
            subscriptions={},
        )

        result = get_subscriber("user123")
        mock_client.get_subscriber.assert_called_once_with("user123")
        assert result["app_user_id"] == "user123"

    def test_get_subscriber_missing_client(self) -> None:
        # Override patch to return context without client
        ctx = MagicMock()
        ctx.request_context.lifespan_context = {}
        with (
            patch.object(mcp, "get_context", return_value=ctx),
            pytest.raises(RevenueCatClientError, match="RevenueCat client not initialized"),
        ):
            get_subscriber("user123")


class TestOfferingsTools:
    """Test offerings server tools."""

    def test_list_offerings(self, mock_client: MagicMock) -> None:
        mock_client.list_offerings.return_value = [
            Offering(identifier="default", packages=[Package(identifier="monthly")]),
        ]

        result = list_offerings()
        mock_client.list_offerings.assert_called_once()
        assert len(result) == 1
        assert result[0]["identifier"] == "default"

    def test_get_offering(self, mock_client: MagicMock) -> None:
        mock_client.get_offering.return_value = Offering(identifier="premium", packages=[])

        result = get_offering("premium")
        mock_client.get_offering.assert_called_once_with("premium")
        assert result["identifier"] == "premium"


class TestMetricsTools:
    """Test metrics server tools."""

    def test_get_overview_metrics(self, mock_client: MagicMock) -> None:
        mock_client.get_overview_metrics.return_value = OverviewMetrics(
            active_subscribers=10,
            mrr=100.0,
            churn_rate=5.0,
        )

        result = get_overview_metrics()
        mock_client.get_overview_metrics.assert_called_once()
        assert result["active_subscribers"] == 10
        assert result["mrr"] == 100.0

    def test_get_charts(self, mock_client: MagicMock) -> None:
        mock_client.get_charts.return_value = ChartData(
            metric_name="revenue",
            period="day",
            data_points=[ChartDataPoint(date="2024-01-01", value=50.0)],
            total=50.0,
        )

        result = get_charts(
            metric_name="revenue", resolution="day", start_date="2024-01-01", end_date="2024-01-02"
        )
        mock_client.get_charts.assert_called_once_with(
            metric_name="revenue",
            resolution="day",
            start_date="2024-01-01",
            end_date="2024-01-02",
        )
        assert result["total"] == 50.0


class TestTransactionTools:
    """Test transaction server tools."""

    def test_get_transaction_history(self, mock_client: MagicMock) -> None:
        mock_client.get_transaction_history.return_value = [
            Transaction(transaction_id="tx_1", product_id="prod_1"),
        ]

        result = get_transaction_history("user123", limit=50)
        mock_client.get_transaction_history.assert_called_once_with("user123", 50)
        assert len(result) == 1
        assert result[0]["transaction_id"] == "tx_1"


class TestEntitlementTools:
    """Test entitlement server tools."""

    def test_grant_entitlement(self, mock_client: MagicMock) -> None:
        mock_client.grant_entitlement.return_value = EntitlementGrantResult(
            success=True,
            app_user_id="user123",
            entitlement_id="pro",
            message="Granted promo",
        )

        result = grant_entitlement("user123", "pro", "monthly")
        mock_client.grant_entitlement.assert_called_once_with("user123", "pro", "monthly")
        assert result["success"] is True

    def test_revoke_entitlement(self, mock_client: MagicMock) -> None:
        mock_client.revoke_entitlement.return_value = EntitlementGrantResult(
            success=True,
            app_user_id="user123",
            entitlement_id="pro",
            message="Revoked promo",
        )

        result = revoke_entitlement("user123", "pro")
        mock_client.revoke_entitlement.assert_called_once_with("user123", "pro")
        assert result["success"] is True


class TestRefundTools:
    """Test refund server tools."""

    def test_refund_purchase(self, mock_client: MagicMock) -> None:
        mock_client.refund_purchase.return_value = RefundResult(
            success=True,
            app_user_id="user123",
            store_transaction_id="tx_1",
            message="Refunded successfully",
        )

        result = refund_purchase("user123", "tx_1")
        mock_client.refund_purchase.assert_called_once_with("user123", "tx_1")
        assert result["success"] is True


class TestProductTools:
    """Test product server tools."""

    def test_list_products(self, mock_client: MagicMock) -> None:
        mock_client.list_products.return_value = [
            Product(product_id="prod_1", product_type="subscription"),
        ]

        result = list_products()
        mock_client.list_products.assert_called_once()
        assert len(result) == 1
        assert result[0]["product_id"] == "prod_1"


class TestOfferingsWriteTools:
    """Test offerings write server tools."""

    def test_create_offering(self, mock_client: MagicMock) -> None:
        mock_client.create_offering.return_value = {
            "success": True,
            "offering": {"identifier": "new-promo"},
        }

        from revenuecat_mcp.server import create_offering

        result = create_offering(project_id="proj_1", offering_config={"identifier": "new-promo"})
        mock_client.create_offering.assert_called_once_with(
            project_id="proj_1", offering_config={"identifier": "new-promo"}
        )
        assert result["success"] is True

    def test_update_offering(self, mock_client: MagicMock) -> None:
        mock_client.update_offering.return_value = {
            "success": True,
            "offering": {"identifier": "promo-updated"},
        }

        from revenuecat_mcp.server import update_offering

        result = update_offering(
            offering_id="promo", updates={"description": "updated desc"}, project_id="proj_1"
        )
        mock_client.update_offering.assert_called_once_with(
            offering_id="promo", updates={"description": "updated desc"}, project_id="proj_1"
        )
        assert result["success"] is True

    def test_create_package(self, mock_client: MagicMock) -> None:
        mock_client.create_package.return_value = {
            "success": True,
            "package": {"identifier": "pkg-1"},
        }

        from revenuecat_mcp.server import create_package

        result = create_package(
            offering_id="promo", package_config={"identifier": "pkg-1"}, project_id="proj_1"
        )
        mock_client.create_package.assert_called_once_with(
            offering_id="promo", package_config={"identifier": "pkg-1"}, project_id="proj_1"
        )
        assert result["success"] is True

    def test_attach_product(self, mock_client: MagicMock) -> None:
        mock_client.attach_product.return_value = {"success": True, "product": {"id": "prod-1"}}

        from revenuecat_mcp.server import attach_product

        result = attach_product(
            package_id="pkg-1", product_config={"product_id": "prod-1"}, project_id="proj_1"
        )
        mock_client.attach_product.assert_called_once_with(
            package_id="pkg-1", product_config={"product_id": "prod-1"}, project_id="proj_1"
        )
        assert result["success"] is True


class TestServerMain:
    """Test server main entry point."""

    def test_main_calls_mcp_run(self) -> None:
        from revenuecat_mcp.server import main

        with patch.object(mcp, "run") as mock_run:
            main([])
            mock_run.assert_called_once()
