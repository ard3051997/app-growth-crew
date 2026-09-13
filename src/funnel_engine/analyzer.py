"""Core analysis logic for the Funnel Analysis Engine."""

from __future__ import annotations

from typing import Any

from funnel_engine.benchmarks import (
    LEAK_INSIGHTS,
    LOW_REACH_IMPRESSION_FLOOR,
    LOW_REACH_INSIGHT,
    STEP_REVENUE_WEIGHTS,
    STEP_TRANSITIONS,
    get_benchmark_for_transition,
    get_benchmarks,
    get_ltv,
)
from funnel_engine.models import (
    BenchmarkComparison,
    BenchmarkMetric,
    FunnelAnalysis,
    FunnelStep,
    RetentionAnalysis,
    RetentionCohort,
)


class FunnelAnalyzer:
    """Stitches data from multiple sources into funnel analysis."""

    def analyze_funnel(
        self,
        ga4_active_users: dict[str, Any],
        ga4_retention: dict[str, Any],
        ga4_events: dict[str, Any],
        play_store_details: dict[str, Any],
        revenuecat_metrics: dict[str, Any] | None,
        app_id: str,
        app_category: str = "utilities",
        ltv_override: float | None = None,
        analysis_date: str = "today",
    ) -> FunnelAnalysis:
        """
        Build the master funnel steps from raw data and calculate leaks.
        """
        ltv = ltv_override if ltv_override is not None else get_ltv(app_category)

        # 1. Extract raw counts from data sources
        store_impressions = play_store_details.get("store_impressions", 0)
        store_views = play_store_details.get("store_visitors", 0)
        installs = play_store_details.get("installs", 0)
        top_funnel_estimated = play_store_details.get("top_funnel_estimated", False)

        d1_active = ga4_active_users.get("active_users_d1", 0)

        # Event counts
        events = ga4_events.get("events", {})
        onboarding = events.get("tutorial_complete", 0)
        paywall = events.get("paywall_view", 0)
        trial = events.get("trial_start", 0)

        # RevenueCat metrics (or fallback to events if not available)
        if revenuecat_metrics:
            paid = revenuecat_metrics.get("active_subscriptions", 0)
            if paid >= trial:
                paid = int(trial * 0.8)
        else:
            paid = events.get("subscription_start", 0)

        d7_retained = ga4_retention.get("d7_retention_count", 0)
        d30_retained = ga4_retention.get("d30_retention_count", 0)

        # 2. Build step counts
        step_counts = {
            "impression": store_impressions,
            "store_view": store_views,
            "install": installs,
            "d1_active": d1_active,
            "onboarding_complete": onboarding,
            "paywall_view": paywall,
            "trial_start": trial,
            "paid_conversion": paid,
            "d7_retained": d7_retained,
            "d30_retained": d30_retained,
        }

        # 3. Calculate transitions
        all_steps: list[FunnelStep] = []
        leaks: list[FunnelStep] = []

        health_score = 100.0
        total_monthly_revenue_impact = 0.0

        # Steps that use back-calculated benchmark estimates, not real measurements.
        # These names must match the third element of each STEP_TRANSITIONS tuple.
        ESTIMATED_STEPS = {"Impression → Store View", "Store View → Install"}

        for order, (from_step, to_step, transition_name) in enumerate(STEP_TRANSITIONS, 1):
            entered = step_counts.get(from_step, 0)
            completed = step_counts.get(to_step, 0)

            # Mark as no real data when top-of-funnel is estimated from benchmarks
            has_data = (
                entered > 0
                and completed > 0
                and not (top_funnel_estimated and transition_name in ESTIMATED_STEPS)
            )

            conversion_rate = min(1.0, completed / entered) if entered > 0 else 0.0
            benchmark_rate = get_benchmark_for_transition(app_category, transition_name)

            gap = None
            monthly_revenue_impact = 0.0
            priority = "low"
            users_lost_daily = 0

            if benchmark_rate is not None and has_data:
                gap = conversion_rate - benchmark_rate

                if gap < 0:
                    # We are below benchmark. Calculate leak cost.
                    # Gap is the missing conversion rate.
                    # Missed users = entered * abs(gap)
                    missed_users = entered * abs(gap)

                    # Estimate monthly impact (assuming counts are daily or weekly,
                    # but here we just multiply missed users by LTV for a rough impact)
                    # To be precise, we need to know the time window of the data.
                    # Let's assume the data is for a 30-day window.
                    monthly_revenue_impact = missed_users * ltv
                    users_lost_daily = int(missed_users / 30)

                    if monthly_revenue_impact > 5000:
                        priority = "critical"
                    elif monthly_revenue_impact > 1000:
                        priority = "high"
                    elif monthly_revenue_impact > 100:
                        priority = "medium"

                    total_monthly_revenue_impact += monthly_revenue_impact

                    # Deduct from health score
                    gap_severity = abs(gap) / benchmark_rate
                    weight = STEP_REVENUE_WEIGHTS.get(transition_name, 1.0)
                    health_score -= gap_severity * weight * 20

            insight = (
                LEAK_INSIGHTS.get(transition_name, "")
                if gap and gap < 0
                else "Performing at or above benchmark."
            )
            # Raw reach and conversion-rate are different problems that need
            # different fixes (see docs/growth_diagnostics_playbook.md §1) --
            # when impression volume itself is critically low, that diagnosis
            # takes priority over a CTR-ratio reading of the same step, which
            # would otherwise misleadingly point at a creative fix instead of
            # a targeting one.
            is_low_reach = (
                from_step == "impression" and has_data and 0 < entered < LOW_REACH_IMPRESSION_FLOOR
            )
            if is_low_reach:
                insight = LOW_REACH_INSIGHT.format(floor=LOW_REACH_IMPRESSION_FLOOR)
                priority = "medium" if priority == "low" else priority
            if not has_data:
                insight = "Insufficient data to analyze this step."

            step = FunnelStep(
                name=transition_name,
                step_order=order,
                users_entered=entered,
                users_completed=completed,
                conversion_rate=conversion_rate,
                benchmark_rate=benchmark_rate,
                gap=gap,
                users_lost_daily=users_lost_daily,
                monthly_revenue_impact=monthly_revenue_impact,
                priority=priority,
                insight=insight,
                has_data=has_data,
            )

            all_steps.append(step)
            if (gap and gap < 0 and has_data) or is_low_reach:
                leaks.append(step)

        health_score = max(0.0, min(100.0, health_score))

        # Sort leaks by revenue impact descending
        leaks.sort(key=lambda x: x.monthly_revenue_impact, reverse=True)

        data_sources = ["play_store_mcp", "analytics_mcp"]
        if revenuecat_metrics:
            data_sources.append("revenuecat_mcp")

        summary = (
            f"Funnel Health Score: {int(health_score)}/100. "
            f"Identified {len(leaks)} leaks with a total estimated monthly revenue impact of ${total_monthly_revenue_impact:,.2f}."
        )

        return FunnelAnalysis(
            analysis_date=analysis_date,
            app_id=app_id,
            app_category=app_category,
            funnel_health_score=int(health_score),
            total_monthly_revenue_impact=total_monthly_revenue_impact,
            ltv_used=ltv,
            leaks=leaks,
            all_steps=all_steps,
            data_sources=data_sources,
            summary=summary,
        )

    def analyze_retention(
        self,
        ga4_retention: dict[str, Any],
        ga4_acquisition: dict[str, Any],
        app_id: str,
        app_category: str = "utilities",
        analysis_date: str = "today",
    ) -> RetentionAnalysis:
        """
        Analyze retention curves and compare to benchmarks.
        """
        benchmarks = get_benchmarks(app_category)
        d1_benchmark = benchmarks.get("d1_retention", 0.0)
        d7_benchmark = benchmarks.get("d7_retention", 0.0)
        d30_benchmark = benchmarks.get("d30_retention", 0.0)

        d1_rate = ga4_retention.get("d1_retention_rate", 0.0)
        d7_rate = ga4_retention.get("d7_retention_rate", 0.0)
        d30_rate = ga4_retention.get("d30_retention_rate", 0.0)

        # Calculate trend (simple comparison)
        trend = "stable"
        if d7_rate > d7_benchmark and d30_rate > d30_benchmark:
            trend = "improving"
            trend_detail = "Retention is trending above category benchmarks."
        elif d7_rate < d7_benchmark and d30_rate < d30_benchmark:
            trend = "declining"
            trend_detail = "Retention is dropping below category benchmarks."
        else:
            trend_detail = "Retention is mixed compared to benchmarks."

        cohorts_data = ga4_retention.get("cohorts", [])
        cohorts = [
            RetentionCohort(
                period=c.get("period", "Unknown"),
                d1_retention=c.get("d1_retention", 0.0),
                d7_retention=c.get("d7_retention", 0.0),
                d30_retention=c.get("d30_retention", 0.0),
                new_users=c.get("new_users", 0),
                source=c.get("source", "all"),
            )
            for c in cohorts_data
        ]

        summary = f"D1: {d1_rate:.1%}, D7: {d7_rate:.1%}, D30: {d30_rate:.1%}. Trend is {trend}."

        return RetentionAnalysis(
            analysis_date=analysis_date,
            app_id=app_id,
            app_category=app_category,
            d1_rate=d1_rate,
            d7_rate=d7_rate,
            d30_rate=d30_rate,
            d1_benchmark=d1_benchmark,
            d7_benchmark=d7_benchmark,
            d30_benchmark=d30_benchmark,
            trend=trend,
            trend_detail=trend_detail,
            cohorts=cohorts,
            retention_by_source=ga4_acquisition.get("retention_by_source", []),
            data_sources=["analytics_mcp"],
            summary=summary,
        )

    def compare_benchmarks(
        self,
        ga4_data: dict[str, Any],
        revenuecat_data: dict[str, Any] | None,
        play_store_data: dict[str, Any],
        app_id: str,
        app_category: str = "utilities",
        analysis_date: str = "today",
    ) -> BenchmarkComparison:
        """
        Compare all available metrics to category benchmarks.
        """
        benchmarks = get_benchmarks(app_category)

        metrics = []
        strengths = []
        weaknesses = []

        # D1 Retention
        d1 = ga4_data.get("d1_retention_rate", 0.0)
        d1_bench = benchmarks.get("d1_retention", 0.0)
        gap = d1 - d1_bench
        metrics.append(
            BenchmarkMetric(
                metric_name="Day 1 Retention",
                metric_key="d1_retention",
                your_value=d1,
                benchmark_value=d1_bench,
                gap=gap,
                gap_percent=(gap / d1_bench) if d1_bench > 0 else 0.0,
                rating="excellent" if gap > 0.05 else "poor" if gap < -0.05 else "average",
                insight="Strong onboarding" if gap > 0 else "Onboarding needs work",
            )
        )

        # Store Conversion
        impressions = play_store_data.get("store_impressions", 0)
        installs = play_store_data.get("installs", 0)
        store_conv = installs / impressions if impressions > 0 else 0.0
        store_conv_bench = benchmarks.get("store_conversion_rate", 0.0)
        gap = store_conv - store_conv_bench
        metrics.append(
            BenchmarkMetric(
                metric_name="Store Conversion Rate",
                metric_key="store_conversion",
                your_value=store_conv,
                benchmark_value=store_conv_bench,
                gap=gap,
                gap_percent=(gap / store_conv_bench) if store_conv_bench > 0 else 0.0,
                rating="excellent" if gap > 0.05 else "poor" if gap < -0.05 else "average",
                insight="ASO is performing well" if gap > 0 else "ASO requires optimization",
            )
        )

        # LTV
        if revenuecat_data:
            ltv = revenuecat_data.get("estimated_ltv", 0.0)
            ltv_bench = benchmarks.get("average_ltv_usd", 0.0)
            gap = ltv - ltv_bench
            metrics.append(
                BenchmarkMetric(
                    metric_name="Average LTV",
                    metric_key="average_ltv_usd",
                    your_value=ltv,
                    benchmark_value=ltv_bench,
                    gap=gap,
                    gap_percent=(gap / ltv_bench) if ltv_bench > 0 else 0.0,
                    rating="excellent" if gap > 2.0 else "poor" if gap < -2.0 else "average",
                    insight="High monetization" if gap > 0 else "Monetization needs work",
                )
            )

        for m in metrics:
            if m.gap > 0:
                strengths.append(m.metric_name)
            else:
                weaknesses.append(m.metric_name)

        percentile = 50 + int((len(strengths) - len(weaknesses)) * 10)
        percentile = max(0, min(100, percentile))

        summary = f"Overall percentile: {percentile}. {len(strengths)} strengths, {len(weaknesses)} weaknesses."

        data_sources = ["analytics_mcp", "play_store_mcp"]
        if revenuecat_data:
            data_sources.append("revenuecat_mcp")

        return BenchmarkComparison(
            analysis_date=analysis_date,
            app_id=app_id,
            app_category=app_category,
            overall_percentile=percentile,
            metrics=metrics,
            strengths=strengths,
            weaknesses=weaknesses,
            data_sources=data_sources,
            summary=summary,
        )
