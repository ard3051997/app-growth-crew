"""Pydantic models for AdMob MCP Server."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AdMobAccount(BaseModel):
    """AdMob account information."""

    account_id: str = Field(..., description="AdMob account ID (pub-XXXXXXXXXXXXXXXX)")
    name: str | None = Field(None, description="Account display name")
    publisher_id: str | None = Field(None, description="Publisher ID")
    reporting_time_zone: str | None = Field(None, description="Reporting timezone")
    currency_code: str | None = Field(None, description="Currency code (e.g., USD)")


class AdUnit(BaseModel):
    """AdMob ad unit."""

    ad_unit_id: str = Field(..., description="Ad unit ID")
    name: str | None = Field(None, description="Ad unit display name")
    app_id: str | None = Field(None, description="Associated app ID")
    ad_format: str | None = Field(
        None, description="Ad format (BANNER, INTERSTITIAL, REWARDED, NATIVE, APP_OPEN)"
    )
    ad_types: list[str] = Field(default_factory=list, description="Ad types served")


class AdMobApp(BaseModel):
    """App linked to AdMob."""

    app_id: str = Field(..., description="AdMob app ID")
    name: str | None = Field(None, description="App display name")
    platform: str | None = Field(None, description="Platform (ANDROID, IOS)")
    linked_app_store_id: str | None = Field(None, description="Store app ID / package name")
    app_approval_state: str | None = Field(None, description="Approval state")


class ReportRow(BaseModel):
    """A single row in an AdMob report."""

    dimensions: dict[str, str] = Field(default_factory=dict, description="Dimension values")
    metrics: dict[str, Any] = Field(default_factory=dict, description="Metric values")


class NetworkReport(BaseModel):
    """AdMob network report result."""

    account_id: str = Field(..., description="AdMob account ID")
    report_type: str = Field("network", description="Report type")
    date_range: str = Field(..., description="Date range of the report")
    rows: list[ReportRow] = Field(default_factory=list, description="Report data rows")
    totals: dict[str, Any] | None = Field(None, description="Totals row")


class MediationReport(BaseModel):
    """AdMob mediation report result."""

    account_id: str = Field(..., description="AdMob account ID")
    report_type: str = Field("mediation", description="Report type")
    date_range: str = Field(..., description="Date range of the report")
    rows: list[ReportRow] = Field(default_factory=list, description="Report data rows")
    totals: dict[str, Any] | None = Field(None, description="Totals row")


class EarningsSummary(BaseModel):
    """Summarized earnings across time periods."""

    account_id: str = Field(..., description="AdMob account ID")
    currency: str = Field("USD", description="Currency code")
    today: float = Field(0.0, description="Today's estimated earnings")
    yesterday: float = Field(0.0, description="Yesterday's earnings")
    last_7_days: float = Field(0.0, description="Last 7 days earnings")
    last_30_days: float = Field(0.0, description="Last 30 days earnings")
    this_month: float = Field(0.0, description="Current month earnings")
    last_month: float = Field(0.0, description="Last month earnings")
    impressions_today: int = Field(0, description="Today's impressions")
    clicks_today: int = Field(0, description="Today's clicks")
    ecpm_today: float = Field(0.0, description="Today's eCPM")
