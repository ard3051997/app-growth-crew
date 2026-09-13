"""Pydantic models for Analytics MCP Server."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DimensionValue(BaseModel):
    """A single dimension value in a report row."""

    name: str = Field(..., description="Dimension name")
    value: str = Field(..., description="Dimension value")


class MetricValue(BaseModel):
    """A single metric value in a report row."""

    name: str = Field(..., description="Metric name")
    value: str = Field(..., description="Metric value (numeric as string)")


class ReportRow(BaseModel):
    """A single row in a GA4 report."""

    dimensions: list[DimensionValue] = Field(default_factory=list, description="Dimension values")
    metrics: list[MetricValue] = Field(default_factory=list, description="Metric values")


class AnalyticsReport(BaseModel):
    """A GA4 analytics report result."""

    property_id: str = Field(..., description="GA4 property ID")
    report_name: str = Field(..., description="Report name/type")
    date_range: str = Field(..., description="Date range of the report")
    row_count: int = Field(0, description="Total row count")
    rows: list[ReportRow] = Field(default_factory=list, description="Report rows")
    totals: dict[str, str] | None = Field(None, description="Total values for metrics")


class RealtimeReport(BaseModel):
    """A GA4 realtime report."""

    property_id: str = Field(..., description="GA4 property ID")
    active_users: int = Field(0, description="Current active users")
    rows: list[ReportRow] = Field(default_factory=list, description="Realtime data rows")


class ActiveUsersReport(BaseModel):
    """Active users report (DAU/WAU/MAU)."""

    property_id: str = Field(..., description="GA4 property ID")
    date_range: str = Field(..., description="Date range")
    daily_active_users: list[dict[str, Any]] = Field(
        default_factory=list, description="DAU per day"
    )
    total_users: int = Field(0, description="Total unique users in period")
    average_dau: float = Field(0.0, description="Average DAU over period")


class AcquisitionReport(BaseModel):
    """User acquisition report by source/medium."""

    property_id: str = Field(..., description="GA4 property ID")
    date_range: str = Field(..., description="Date range")
    channels: list[dict[str, Any]] = Field(
        default_factory=list, description="Acquisition channels with metrics"
    )
    total_new_users: int = Field(0, description="Total new users")


class RetentionReport(BaseModel):
    """Cohort retention report."""

    property_id: str = Field(..., description="GA4 property ID")
    date_range: str = Field(..., description="Date range")
    cohorts: list[dict[str, Any]] = Field(default_factory=list, description="Retention cohorts")


class EventReport(BaseModel):
    """Top events report."""

    property_id: str = Field(..., description="GA4 property ID")
    date_range: str = Field(..., description="Date range")
    events: list[dict[str, Any]] = Field(default_factory=list, description="Events with counts")
    total_events: int = Field(0, description="Total event count")


class DemographicsReport(BaseModel):
    """User demographics report."""

    property_id: str = Field(..., description="GA4 property ID")
    date_range: str = Field(..., description="Date range")
    countries: list[dict[str, Any]] = Field(default_factory=list, description="Users by country")
    devices: list[dict[str, Any]] = Field(
        default_factory=list, description="Users by device category"
    )
    os_versions: list[dict[str, Any]] = Field(
        default_factory=list, description="Users by OS version"
    )


class RevenueReport(BaseModel):
    """Revenue breakdown report."""

    property_id: str = Field(..., description="GA4 property ID")
    date_range: str = Field(..., description="Date range")
    total_revenue: float = Field(0.0, description="Total revenue")
    purchase_revenue: float = Field(0.0, description="In-app purchase revenue")
    ad_revenue: float = Field(0.0, description="Ad revenue")
    daily_revenue: list[dict[str, Any]] = Field(default_factory=list, description="Revenue per day")


class ScreenViewReport(BaseModel):
    """Screen/page views report."""

    property_id: str = Field(..., description="GA4 property ID")
    date_range: str = Field(..., description="Date range")
    screens: list[dict[str, Any]] = Field(
        default_factory=list, description="Screen views with counts"
    )
    total_screen_views: int = Field(0, description="Total screen views")
