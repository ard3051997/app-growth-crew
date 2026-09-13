"""Pydantic models for RevenueCat MCP Server."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - Pydantic needs this at runtime
from typing import Any

from pydantic import BaseModel, Field


class Entitlement(BaseModel):
    """A subscriber's entitlement."""

    entitlement_id: str = Field(..., description="Entitlement identifier")
    product_id: str | None = Field(None, description="Product that granted this entitlement")
    expires_date: datetime | None = Field(None, description="Expiration date")
    purchase_date: datetime | None = Field(None, description="Purchase date")
    is_active: bool = Field(False, description="Whether entitlement is currently active")
    will_renew: bool = Field(False, description="Whether entitlement will auto-renew")
    period_type: str | None = Field(None, description="Period type (normal, trial, intro)")
    store: str | None = Field(None, description="Store (play_store, app_store, stripe, etc.)")
    is_sandbox: bool = Field(False, description="Whether from sandbox environment")
    unsubscribe_detected_at: datetime | None = Field(None, description="Unsubscribe detection time")
    billing_issues_detected_at: datetime | None = Field(
        None, description="Billing issue detection time"
    )


class Subscription(BaseModel):
    """A subscriber's subscription."""

    product_id: str = Field(..., description="Product identifier")
    expires_date: datetime | None = Field(None, description="Expiration date")
    purchase_date: datetime | None = Field(None, description="Purchase date")
    original_purchase_date: datetime | None = Field(None, description="Original purchase date")
    store: str | None = Field(None, description="Store of origin")
    is_sandbox: bool = Field(False, description="Whether from sandbox")
    period_type: str | None = Field(None, description="Period type")
    unsubscribe_detected_at: datetime | None = Field(None, description="Unsubscribe detection")
    billing_issues_detected_at: datetime | None = Field(None, description="Billing issue detection")
    refunded_at: datetime | None = Field(None, description="Refund time if refunded")
    auto_resume_date: datetime | None = Field(None, description="Auto-resume date if paused")


class NonSubscription(BaseModel):
    """A non-subscription purchase."""

    product_id: str = Field(..., description="Product identifier")
    purchase_date: datetime | None = Field(None, description="Purchase date")
    store: str | None = Field(None, description="Store of origin")
    is_sandbox: bool = Field(False, description="Whether from sandbox")
    id: str | None = Field(None, description="Transaction identifier")


class Subscriber(BaseModel):
    """Full subscriber profile."""

    app_user_id: str = Field(..., description="App user ID")
    original_app_user_id: str | None = Field(None, description="Original app user ID")
    first_seen: datetime | None = Field(None, description="First seen date")
    last_seen: datetime | None = Field(None, description="Last seen date")
    entitlements: dict[str, Entitlement] = Field(
        default_factory=dict, description="Active entitlements"
    )
    subscriptions: dict[str, Subscription] = Field(
        default_factory=dict, description="Subscription history"
    )
    non_subscriptions: dict[str, list[NonSubscription]] = Field(
        default_factory=dict, description="Non-subscription purchases"
    )
    management_url: str | None = Field(None, description="Subscription management URL")
    original_purchase_date: datetime | None = Field(None, description="Original purchase date")


class Package(BaseModel):
    """An offering package."""

    identifier: str = Field(..., description="Package identifier")
    platform_product_identifier: str | None = Field(
        None, description="Platform-specific product ID"
    )
    display_string: str | None = Field(None, description="Display string for the package")


class Offering(BaseModel):
    """A RevenueCat offering."""

    identifier: str = Field(..., description="Offering identifier")
    description: str | None = Field(None, description="Offering description")
    is_current: bool = Field(False, description="Whether this is the current offering")
    packages: list[Package] = Field(default_factory=list, description="Packages in this offering")
    metadata: dict[str, Any] | None = Field(None, description="Offering metadata")


class OverviewMetrics(BaseModel):
    """Revenue overview metrics."""

    active_subscribers: int = Field(0, description="Total active subscribers")
    active_trials: int = Field(0, description="Active trial users")
    mrr: float = Field(0.0, description="Monthly Recurring Revenue in USD")
    revenue: float = Field(0.0, description="Total revenue in period")
    new_subscribers: int = Field(0, description="New subscribers in period")
    churn_rate: float | None = Field(None, description="Churn rate percentage")
    refund_rate: float | None = Field(None, description="Refund rate percentage")
    active_users: int = Field(0, description="Active users (installs)")


class Transaction(BaseModel):
    """A RevenueCat transaction."""

    transaction_id: str = Field(..., description="Transaction identifier")
    product_id: str | None = Field(None, description="Product identifier")
    app_user_id: str | None = Field(None, description="App user ID")
    purchased_at: datetime | None = Field(None, description="Purchase time")
    revenue_in_usd: float | None = Field(None, description="Revenue in USD")
    store: str | None = Field(None, description="Store (play_store, app_store, etc.)")
    is_trial: bool = Field(False, description="Whether this is a trial conversion")
    is_renewal: bool = Field(False, description="Whether this is a renewal")
    was_refunded: bool = Field(False, description="Whether this was refunded")
    country: str | None = Field(None, description="Country code")


class Product(BaseModel):
    """A RevenueCat product configuration."""

    product_id: str = Field(..., description="Product identifier")
    store_identifier: str | None = Field(None, description="Store-specific product ID")
    product_type: str | None = Field(
        None, description="Product type (subscription, non_subscription)"
    )
    app_id: str | None = Field(None, description="App identifier")
    display_name: str | None = Field(None, description="Display name")
    created_at: datetime | None = Field(None, description="Creation date")


class ChartDataPoint(BaseModel):
    """A single data point in a chart."""

    date: str = Field(..., description="Date (YYYY-MM-DD)")
    value: float = Field(0.0, description="Metric value")
    label: str | None = Field(None, description="Optional label")


class ChartData(BaseModel):
    """Chart data for revenue/subscriber trends."""

    metric_name: str = Field(..., description="Name of the metric")
    period: str = Field(..., description="Period (daily, weekly, monthly)")
    data_points: list[ChartDataPoint] = Field(default_factory=list, description="Data points")
    total: float | None = Field(None, description="Total across period")


class EntitlementGrantResult(BaseModel):
    """Result of granting/revoking an entitlement."""

    success: bool = Field(..., description="Whether operation succeeded")
    app_user_id: str = Field(..., description="App user ID")
    entitlement_id: str = Field(..., description="Entitlement identifier")
    message: str = Field(..., description="Status message")
    error: str | None = Field(None, description="Error details if failed")


class RefundResult(BaseModel):
    """Result of a refund operation."""

    success: bool = Field(..., description="Whether refund succeeded")
    app_user_id: str = Field(..., description="App user ID")
    store_transaction_id: str = Field(..., description="Store transaction ID")
    message: str = Field(..., description="Status message")
    error: str | None = Field(None, description="Error details if failed")
