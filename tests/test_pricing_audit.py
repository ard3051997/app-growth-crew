"""Tests for the cross-app regional pricing completeness audit."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app_manager import pricing_audit as pricing_audit_module
from app_manager.credential_store import AppCredentials
from app_manager.pricing_audit import audit_regional_pricing_completeness
from play_store_mcp.client import PlayStoreClientError
from play_store_mcp.models import InAppProduct, SubscriptionProduct

PACKAGE = "com.example.app"
TARGET_COUNTRIES = frozenset({"US", "GB", "DE"})


def _credentials(*, has_play_store: bool = True) -> AppCredentials:
    return AppCredentials(
        package_name=PACKAGE,
        google_credentials_path="fake-service-account.json" if has_play_store else None,
    )


def test_reports_missing_target_countries_for_managed_products_and_subscriptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pricing_audit_module, "get_app_credentials", lambda _package: _credentials()
    )

    mock_client = MagicMock()
    mock_client.list_in_app_products.return_value = [
        InAppProduct(sku="premium_lifetime", package_name=PACKAGE, product_type="managedProduct")
    ]
    mock_client.get_in_app_product.return_value = InAppProduct(
        sku="premium_lifetime",
        package_name=PACKAGE,
        product_type="managedProduct",
        prices={"US": {"priceMicros": "9990000", "currency": "USD"}},
    )
    mock_client.list_subscriptions.return_value = [
        SubscriptionProduct(
            product_id="premium_monthly",
            package_name=PACKAGE,
            base_plans=[
                {
                    "basePlanId": "monthly",
                    "regionalConfigs": [
                        {"regionCode": "US", "price": {"units": "9", "currencyCode": "USD"}},
                        {"regionCode": "GB", "price": {"units": "8", "currencyCode": "GBP"}},
                    ],
                }
            ],
        )
    ]
    monkeypatch.setattr(pricing_audit_module, "PlayStoreClient", lambda **_kwargs: mock_client)

    result = audit_regional_pricing_completeness(PACKAGE, target_countries=TARGET_COUNTRIES)

    assert result["status"] == "ok"
    assert result["products_checked"] == 2
    findings_by_sku = {f["sku"]: f for f in result["findings"]}

    assert findings_by_sku["premium_lifetime"]["missing_countries"] == ["DE", "GB"]
    assert findings_by_sku["premium_lifetime"]["experiment_type"] == "pricing_experiment"
    assert findings_by_sku["premium_lifetime"]["capability"] == "planning_only"

    assert findings_by_sku["premium_monthly"]["missing_countries"] == ["DE"]
    assert findings_by_sku["premium_monthly"]["product_type"] == "subscription"


def test_reports_no_findings_when_all_target_countries_are_covered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pricing_audit_module, "get_app_credentials", lambda _package: _credentials()
    )

    mock_client = MagicMock()
    mock_client.list_in_app_products.return_value = []
    mock_client.list_subscriptions.return_value = [
        SubscriptionProduct(
            product_id="premium_monthly",
            package_name=PACKAGE,
            base_plans=[
                {
                    "basePlanId": "monthly",
                    "regionalConfigs": [
                        {"regionCode": c, "price": {"units": "9", "currencyCode": "USD"}}
                        for c in TARGET_COUNTRIES
                    ],
                }
            ],
        )
    ]
    monkeypatch.setattr(pricing_audit_module, "PlayStoreClient", lambda **_kwargs: mock_client)

    result = audit_regional_pricing_completeness(PACKAGE, target_countries=TARGET_COUNTRIES)

    assert result["status"] == "ok"
    assert result["findings"] == []


def test_skips_apps_without_play_store_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pricing_audit_module,
        "get_app_credentials",
        lambda _package: _credentials(has_play_store=False),
    )

    result = audit_regional_pricing_completeness(PACKAGE)

    assert result["status"] == "no_play_store_credentials"
    assert result["findings"] == []


def test_reports_play_store_errors_without_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pricing_audit_module, "get_app_credentials", lambda _package: _credentials()
    )

    mock_client = MagicMock()
    mock_client.list_in_app_products.side_effect = PlayStoreClientError("boom")
    monkeypatch.setattr(pricing_audit_module, "PlayStoreClient", lambda **_kwargs: mock_client)

    result = audit_regional_pricing_completeness(PACKAGE)

    assert result["status"].startswith("play_store_error")
    assert result["findings"] == []
