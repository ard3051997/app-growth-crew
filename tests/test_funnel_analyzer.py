"""Tests for FunnelAnalyzer's leak diagnosis, including the low-reach-vs-low-
conversion distinction (docs/growth_diagnostics_playbook.md §1)."""

from __future__ import annotations

from funnel_engine.analyzer import FunnelAnalyzer
from funnel_engine.benchmarks import BENCHMARKS, LOW_REACH_IMPRESSION_FLOOR


def _play_store_details(
    *,
    store_impressions: int,
    store_visitors: int,
    installs: int,
    top_funnel_estimated: bool = False,
) -> dict:
    return {
        "store_impressions": store_impressions,
        "store_visitors": store_visitors,
        "installs": installs,
        "top_funnel_estimated": top_funnel_estimated,
    }


def _analyze(play_store_details: dict, *, category: str = "productivity"):
    return FunnelAnalyzer().analyze_funnel(
        ga4_active_users={"active_users_d1": 0},
        ga4_retention={"d7_retention_count": 0, "d30_retention_count": 0},
        ga4_events={"events": {}},
        play_store_details=play_store_details,
        revenuecat_metrics=None,
        app_id="com.example.app",
        app_category=category,
    )


def _step(analysis, name: str):
    return next(s for s in analysis.all_steps if s.name == name)


class TestReachVsConversionDiagnosis:
    def test_low_ctr_with_healthy_reach_gets_the_creative_insight(self) -> None:
        """Plenty of impressions, but few convert to store views -- a CTR/creative problem."""
        rate = BENCHMARKS["productivity"]["impression_to_store_view"]
        healthy_impressions = LOW_REACH_IMPRESSION_FLOOR * 5
        weak_views = int(healthy_impressions * rate * 0.3)  # well below benchmark ratio
        analysis = _analyze(
            _play_store_details(
                store_impressions=healthy_impressions,
                store_visitors=weak_views,
                installs=weak_views // 2,
            )
        )
        step = _step(analysis, "Impression → Store View")
        assert "reach problem" not in step.insight
        assert "icon" in step.insight.lower() or "tap" in step.insight.lower()
        assert step in analysis.leaks

    def test_low_raw_impressions_gets_the_reach_insight_even_with_a_fine_ratio(self) -> None:
        """Very few impressions but a perfectly healthy CTR -- still a real reach problem."""
        rate = BENCHMARKS["productivity"]["impression_to_store_view"]
        low_impressions = LOW_REACH_IMPRESSION_FLOOR - 1
        good_views = int(low_impressions * rate * 1.5)  # above benchmark ratio
        analysis = _analyze(
            _play_store_details(
                store_impressions=low_impressions,
                store_visitors=good_views,
                installs=good_views // 3,
            )
        )
        step = _step(analysis, "Impression → Store View")
        assert "reach problem" in step.insight
        assert "keyword" in step.insight.lower()
        assert step in analysis.leaks
        assert step.priority in {"medium", "high", "critical"}

    def test_low_raw_impressions_with_a_bad_ratio_still_gets_the_reach_insight(self) -> None:
        """Reach diagnosis takes priority over the ratio-based one for the same step."""
        low_impressions = LOW_REACH_IMPRESSION_FLOOR - 1
        analysis = _analyze(
            _play_store_details(store_impressions=low_impressions, store_visitors=1, installs=0)
        )
        step = _step(analysis, "Impression → Store View")
        assert "reach problem" in step.insight

    def test_estimated_top_funnel_never_triggers_the_reach_insight(self) -> None:
        """A benchmark-estimated (not really-measured) impression count must not be
        diagnosed as a real reach problem -- has_data=False takes priority."""
        analysis = _analyze(
            _play_store_details(
                store_impressions=10,
                store_visitors=5,
                installs=2,
                top_funnel_estimated=True,
            )
        )
        step = _step(analysis, "Impression → Store View")
        assert step.insight == "Insufficient data to analyze this step."
        assert step not in analysis.leaks

    def test_low_store_view_to_install_ratio_gets_the_listing_insight_not_reach(self) -> None:
        rate = BENCHMARKS["productivity"]["store_view_to_install"]
        healthy_views = LOW_REACH_IMPRESSION_FLOOR * 5
        weak_installs = int(healthy_views * rate * 0.2)
        analysis = _analyze(
            _play_store_details(
                store_impressions=healthy_views * 3,
                store_visitors=healthy_views,
                installs=weak_installs,
            )
        )
        step = _step(analysis, "Store View → Install")
        assert "screenshot" in step.insight.lower() or "description" in step.insight.lower()
        assert "reach problem" not in step.insight.lower()

    def test_healthy_funnel_across_the_board_has_no_leaks(self) -> None:
        healthy_impressions = LOW_REACH_IMPRESSION_FLOOR * 10
        views = int(
            healthy_impressions * BENCHMARKS["productivity"]["impression_to_store_view"] * 1.2
        )
        installs = int(views * BENCHMARKS["productivity"]["store_view_to_install"] * 1.2)
        analysis = _analyze(
            _play_store_details(
                store_impressions=healthy_impressions, store_visitors=views, installs=installs
            )
        )
        acquisition_leaks = [
            leak
            for leak in analysis.leaks
            if leak.name in {"Impression → Store View", "Store View → Install"}
        ]
        assert acquisition_leaks == []
