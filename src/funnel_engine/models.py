"""Pydantic models for Funnel Analysis Engine output."""

from __future__ import annotations

from pydantic import BaseModel, Field


class FunnelStep(BaseModel):
    """A single step in the master funnel with leak analysis."""

    name: str = Field(..., description="Step transition name, e.g. 'Store View → Install'")
    step_order: int = Field(..., description="Position in the funnel (1-based)")
    users_entered: int = Field(0, description="Users who entered this step")
    users_completed: int = Field(0, description="Users who completed this step")
    conversion_rate: float = Field(0.0, description="Actual conversion rate (0.0 to 1.0)")
    benchmark_rate: float | None = Field(None, description="Category benchmark rate")
    gap: float | None = Field(None, description="Gap vs benchmark (negative = below benchmark)")
    users_lost_daily: int = Field(0, description="Estimated users lost per day at this step")
    monthly_revenue_impact: float = Field(
        0.0, description="Estimated monthly revenue impact of the leak"
    )
    priority: str = Field("low", description="Priority level: critical, high, medium, low")
    insight: str = Field("", description="Human-readable insight about this leak")
    has_data: bool = Field(True, description="Whether real data was available for this step")


class FunnelAnalysis(BaseModel):
    """Complete funnel analysis output matching analysis_engine.md Module 1."""

    analysis_date: str = Field(..., description="Date of analysis (YYYY-MM-DD)")
    app_id: str = Field(..., description="App package name or identifier")
    app_category: str = Field(..., description="App category used for benchmarking")
    funnel_health_score: int = Field(0, description="Overall funnel health score (0-100)")
    total_monthly_revenue_impact: float = Field(
        0.0, description="Total estimated monthly revenue lost to funnel leaks"
    )
    ltv_used: float = Field(0.0, description="LTV value used for leak cost calculation")
    leaks: list[FunnelStep] = Field(
        default_factory=list,
        description="Funnel steps ranked by revenue impact (worst leak first)",
    )
    all_steps: list[FunnelStep] = Field(
        default_factory=list,
        description="All funnel steps in order",
    )
    data_sources: list[str] = Field(
        default_factory=list,
        description="MCP servers that contributed data",
    )
    summary: str = Field("", description="Executive summary of the funnel analysis")


class RetentionCohort(BaseModel):
    """Retention data for a single cohort or time period."""

    period: str = Field(..., description="Time period label (e.g. 'Week of Jun 1')")
    d1_retention: float = Field(0.0, description="Day 1 retention rate")
    d7_retention: float = Field(0.0, description="Day 7 retention rate")
    d30_retention: float = Field(0.0, description="Day 30 retention rate")
    new_users: int = Field(0, description="New users in this cohort")
    source: str = Field("all", description="Acquisition source for this cohort")


class RetentionAnalysis(BaseModel):
    """Retention analysis output matching analysis_engine.md Module 3."""

    analysis_date: str = Field(..., description="Date of analysis")
    app_id: str = Field(..., description="App identifier")
    app_category: str = Field(..., description="App category for benchmarking")

    # Aggregate rates
    d1_rate: float = Field(0.0, description="Overall Day 1 retention rate")
    d7_rate: float = Field(0.0, description="Overall Day 7 retention rate")
    d30_rate: float = Field(0.0, description="Overall Day 30 retention rate")

    # Benchmarks
    d1_benchmark: float = Field(0.0, description="Category D1 benchmark")
    d7_benchmark: float = Field(0.0, description="Category D7 benchmark")
    d30_benchmark: float = Field(0.0, description="Category D30 benchmark")

    # Trend
    trend: str = Field("stable", description="Retention trend: improving, declining, or stable")
    trend_detail: str = Field("", description="Explanation of trend")

    # Cohort data
    cohorts: list[RetentionCohort] = Field(default_factory=list, description="Retention by cohort")

    # By source
    retention_by_source: list[dict] = Field(
        default_factory=list,
        description="Retention broken down by acquisition source",
    )

    data_sources: list[str] = Field(default_factory=list)
    summary: str = Field("", description="Executive summary")


class BenchmarkMetric(BaseModel):
    """A single metric compared to its benchmark."""

    metric_name: str = Field(..., description="Human-readable metric name")
    metric_key: str = Field(..., description="Internal metric key")
    your_value: float = Field(0.0, description="Your app's value")
    benchmark_value: float = Field(0.0, description="Category benchmark value")
    gap: float = Field(0.0, description="Difference (your - benchmark)")
    gap_percent: float = Field(0.0, description="Gap as percentage of benchmark")
    rating: str = Field(
        "average", description="Rating: excellent, good, average, below_average, poor"
    )
    insight: str = Field("", description="Brief insight about this metric")


class BenchmarkComparison(BaseModel):
    """Full benchmark comparison output matching analysis_engine.md Module 4."""

    analysis_date: str = Field(..., description="Date of analysis")
    app_id: str = Field(..., description="App identifier")
    app_category: str = Field(..., description="Category used for comparison")
    overall_percentile: int = Field(50, description="Overall percentile ranking (0-100)")
    metrics: list[BenchmarkMetric] = Field(
        default_factory=list, description="Individual metric comparisons"
    )
    strengths: list[str] = Field(
        default_factory=list, description="Areas where app exceeds benchmarks"
    )
    weaknesses: list[str] = Field(
        default_factory=list, description="Areas where app is below benchmarks"
    )
    data_sources: list[str] = Field(default_factory=list)
    summary: str = Field("", description="Executive summary")
