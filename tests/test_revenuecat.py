"""Tests for RevenueCat MCP Server."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from revenuecat_mcp.client import RevenueCatClient, RevenueCatClientError, _is_active, _parse_iso
from revenuecat_mcp.models import (
    ChartData,
    ChartDataPoint,
    Entitlement,
    EntitlementGrantResult,
    Offering,
    OverviewMetrics,
    Package,
    Product,
    RefundResult,
    Subscriber,
    Subscription,
    Transaction,
)


class TestParseIso:
    """Tests for ISO timestamp parsing."""

    def test_parse_valid_iso(self) -> None:
        result = _parse_iso("2024-01-15T10:30:00Z")
        assert result is not None
        assert result.year == 2024
        assert result.month == 1

    def test_parse_none(self) -> None:
        assert _parse_iso(None) is None

    def test_parse_empty(self) -> None:
        assert _parse_iso("") is None

    def test_parse_invalid(self) -> None:
        assert _parse_iso("not-a-date") is None


class TestIsActive:
    """Tests for entitlement active check."""

    def test_active_future(self) -> None:
        future = "2099-12-31T23:59:59Z"
        assert _is_active(future) is True

    def test_inactive_past(self) -> None:
        past = "2020-01-01T00:00:00Z"
        assert _is_active(past) is False

    def test_none_date(self) -> None:
        assert _is_active(None) is False

    def test_empty_date(self) -> None:
        assert _is_active("") is False


class TestRevenueCatClientInit:
    """Tests for client initialization."""

    def test_init_with_api_key(self) -> None:
        client = RevenueCatClient(api_key="test_key")
        assert client._api_key == "test_key"

    def test_init_from_env(self) -> None:
        with patch.dict("os.environ", {"REVENUECAT_API_KEY": "env_key"}):
            client = RevenueCatClient()
            assert client._api_key == "env_key"

    def test_init_no_key_raises(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(RevenueCatClientError, match="No API key found"):
                RevenueCatClient()


class TestModels:
    """Tests for Pydantic model construction."""

    def test_subscriber_model(self) -> None:
        subscriber = Subscriber(
            app_user_id="user123",
            entitlements={"pro": Entitlement(entitlement_id="pro", is_active=True)},
            subscriptions={"yearly": Subscription(product_id="yearly")},
        )
        assert subscriber.app_user_id == "user123"
        assert subscriber.entitlements["pro"].is_active is True

    def test_offering_model(self) -> None:
        offering = Offering(
            identifier="default",
            is_current=True,
            packages=[Package(identifier="monthly", platform_product_identifier="prod_monthly")],
        )
        assert offering.identifier == "default"
        assert len(offering.packages) == 1

    def test_overview_metrics(self) -> None:
        metrics = OverviewMetrics(
            active_subscribers=1000,
            mrr=5000.50,
            churn_rate=3.2,
        )
        assert metrics.active_subscribers == 1000
        assert metrics.mrr == 5000.50

    def test_transaction_model(self) -> None:
        tx = Transaction(
            transaction_id="tx_123",
            product_id="yearly_sub",
            is_renewal=True,
        )
        assert tx.transaction_id == "tx_123"
        assert tx.is_renewal is True

    def test_chart_data(self) -> None:
        chart = ChartData(
            metric_name="revenue",
            period="day",
            data_points=[
                ChartDataPoint(date="2024-01-01", value=100.0),
                ChartDataPoint(date="2024-01-02", value=200.0),
            ],
            total=300.0,
        )
        assert len(chart.data_points) == 2
        assert chart.total == 300.0

    def test_entitlement_grant_result(self) -> None:
        result = EntitlementGrantResult(
            success=True,
            app_user_id="user1",
            entitlement_id="pro",
            message="Granted",
        )
        assert result.success is True

    def test_refund_result(self) -> None:
        result = RefundResult(
            success=False,
            app_user_id="user1",
            store_transaction_id="GPA.123",
            message="Failed",
            error="Not found",
        )
        assert result.success is False
        assert result.error == "Not found"

    def test_product_model(self) -> None:
        product = Product(
            product_id="prod_123",
            product_type="subscription",
            display_name="Premium Plan",
        )
        assert product.product_type == "subscription"

    def test_model_serialization(self) -> None:
        """Verify models serialize cleanly via model_dump."""
        offering = Offering(
            identifier="test",
            packages=[Package(identifier="pkg1")],
        )
        data = offering.model_dump()
        assert isinstance(data, dict)
        assert data["identifier"] == "test"
        assert isinstance(data["packages"], list)
