"""Funnel Analysis Engine — intelligence layer for mobile app growth analysis.

Stitches data from GA4, Play Store, and RevenueCat to detect funnel leaks,
compute health scores, and benchmark against category averages.
"""

from __future__ import annotations

from funnel_engine.analyzer import FunnelAnalyzer
from funnel_engine.db import get_total_storefront_metrics, init_db
from funnel_engine.models import (
    BenchmarkComparison,
    BenchmarkMetric,
    FunnelAnalysis,
    FunnelStep,
    RetentionAnalysis,
    RetentionCohort,
)

__all__ = [
    "BenchmarkComparison",
    "BenchmarkMetric",
    "FunnelAnalysis",
    "FunnelAnalyzer",
    "FunnelStep",
    "RetentionAnalysis",
    "RetentionCohort",
    "get_total_storefront_metrics",
    "init_db",
]
