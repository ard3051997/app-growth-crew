"""Category benchmark data for mobile app funnel analysis.

Sources:
- Adjust Mobile App Trends Report 2024
- AppsFlyer State of App Marketing 2024
- Liftoff Mobile Ad Creative Index 2024
- RevenueCat State of Subscription Apps 2024
- Statista App Market Benchmarks 2024

All rates are expressed as decimals (e.g., 0.33 = 33%).
Revenue values are in USD.

NOTE: These are industry-wide approximations. Individual results vary
significantly by geography, app maturity, and monetization model.
"""

from __future__ import annotations

from typing import Any

# =============================================================================
# Master Funnel Step Definitions
# =============================================================================

MASTER_FUNNEL_STEPS = [
    "impression",  # Store listing impression
    "store_view",  # Store page view
    "install",  # App installed
    "d1_active",  # Active on Day 1
    "onboarding_complete",  # Completed onboarding flow
    "paywall_view",  # Viewed paywall/pricing screen
    "trial_start",  # Started free trial
    "paid_conversion",  # Converted to paying user
    "d7_retained",  # Retained at Day 7
    "d30_retained",  # Retained at Day 30
]

STEP_TRANSITIONS = [
    ("impression", "store_view", "Impression → Store View"),
    ("store_view", "install", "Store View → Install"),
    ("install", "d1_active", "Install → Day 1 Active"),
    ("d1_active", "onboarding_complete", "Day 1 → Onboarding Complete"),
    ("onboarding_complete", "paywall_view", "Onboarding → Paywall View"),
    ("paywall_view", "trial_start", "Paywall View → Trial Start"),
    ("trial_start", "paid_conversion", "Trial Start → Paid Conversion"),
    ("install", "d7_retained", "Install → Day 7 Retained"),
    ("install", "d30_retained", "Install → Day 30 Retained"),
]

# Revenue-impact weights for health score calculation.
# Higher weights for bottom-of-funnel (BOFU) steps since they're closer to revenue.
STEP_REVENUE_WEIGHTS: dict[str, float] = {
    "Impression → Store View": 0.5,
    "Store View → Install": 1.0,
    "Install → Day 1 Active": 1.5,
    "Day 1 → Onboarding Complete": 2.0,
    "Onboarding → Paywall View": 2.5,
    "Paywall View → Trial Start": 3.0,
    "Trial Start → Paid Conversion": 3.5,
    "Install → Day 7 Retained": 1.5,
    "Install → Day 30 Retained": 1.0,
}

# =============================================================================
# Category Benchmarks
# =============================================================================

CategoryBenchmarks = dict[str, float]

BENCHMARKS: dict[str, CategoryBenchmarks] = {
    "finance": {
        # Acquisition funnel
        "impression_to_store_view": 0.35,
        "store_view_to_install": 0.33,
        "install_to_d1_active": 0.25,
        # Engagement funnel
        "d1_to_onboarding_complete": 0.67,
        "onboarding_to_paywall_view": 0.40,
        "paywall_to_trial_start": 0.15,
        "trial_to_paid": 0.55,
        # Retention
        "d1_retention": 0.22,
        "d7_retention": 0.12,
        "d30_retention": 0.07,
        # Revenue
        "arpu_monthly_usd": 2.50,
        "average_ltv_usd": 18.00,
        # Store
        "store_conversion_rate": 0.33,
    },
    "utilities": {
        "impression_to_store_view": 0.30,
        "store_view_to_install": 0.38,
        "install_to_d1_active": 0.20,
        "d1_to_onboarding_complete": 0.72,
        "onboarding_to_paywall_view": 0.35,
        "paywall_to_trial_start": 0.12,
        "trial_to_paid": 0.50,
        "d1_retention": 0.18,
        "d7_retention": 0.10,
        "d30_retention": 0.06,
        "arpu_monthly_usd": 1.80,
        "average_ltv_usd": 12.00,
        "store_conversion_rate": 0.38,
    },
    "games": {
        "impression_to_store_view": 0.40,
        "store_view_to_install": 0.42,
        "install_to_d1_active": 0.30,
        "d1_to_onboarding_complete": 0.55,
        "onboarding_to_paywall_view": 0.25,
        "paywall_to_trial_start": 0.08,
        "trial_to_paid": 0.40,
        "d1_retention": 0.28,
        "d7_retention": 0.12,
        "d30_retention": 0.05,
        "arpu_monthly_usd": 0.80,
        "average_ltv_usd": 6.50,
        "store_conversion_rate": 0.42,
    },
    "health_fitness": {
        "impression_to_store_view": 0.32,
        "store_view_to_install": 0.30,
        "install_to_d1_active": 0.27,
        "d1_to_onboarding_complete": 0.60,
        "onboarding_to_paywall_view": 0.45,
        "paywall_to_trial_start": 0.20,
        "trial_to_paid": 0.52,
        "d1_retention": 0.24,
        "d7_retention": 0.14,
        "d30_retention": 0.08,
        "arpu_monthly_usd": 3.50,
        "average_ltv_usd": 25.00,
        "store_conversion_rate": 0.30,
    },
    "productivity": {
        "impression_to_store_view": 0.28,
        "store_view_to_install": 0.35,
        "install_to_d1_active": 0.22,
        "d1_to_onboarding_complete": 0.65,
        "onboarding_to_paywall_view": 0.38,
        "paywall_to_trial_start": 0.18,
        "trial_to_paid": 0.58,
        "d1_retention": 0.20,
        "d7_retention": 0.11,
        "d30_retention": 0.06,
        "arpu_monthly_usd": 2.80,
        "average_ltv_usd": 20.00,
        "store_conversion_rate": 0.35,
    },
    "education": {
        "impression_to_store_view": 0.33,
        "store_view_to_install": 0.36,
        "install_to_d1_active": 0.24,
        "d1_to_onboarding_complete": 0.58,
        "onboarding_to_paywall_view": 0.30,
        "paywall_to_trial_start": 0.14,
        "trial_to_paid": 0.48,
        "d1_retention": 0.21,
        "d7_retention": 0.10,
        "d30_retention": 0.05,
        "arpu_monthly_usd": 2.00,
        "average_ltv_usd": 14.00,
        "store_conversion_rate": 0.36,
    },
    "social": {
        "impression_to_store_view": 0.38,
        "store_view_to_install": 0.40,
        "install_to_d1_active": 0.32,
        "d1_to_onboarding_complete": 0.50,
        "onboarding_to_paywall_view": 0.20,
        "paywall_to_trial_start": 0.10,
        "trial_to_paid": 0.35,
        "d1_retention": 0.30,
        "d7_retention": 0.15,
        "d30_retention": 0.08,
        "arpu_monthly_usd": 1.20,
        "average_ltv_usd": 8.00,
        "store_conversion_rate": 0.40,
    },
    "shopping": {
        "impression_to_store_view": 0.30,
        "store_view_to_install": 0.32,
        "install_to_d1_active": 0.26,
        "d1_to_onboarding_complete": 0.62,
        "onboarding_to_paywall_view": 0.15,
        "paywall_to_trial_start": 0.08,
        "trial_to_paid": 0.45,
        "d1_retention": 0.23,
        "d7_retention": 0.11,
        "d30_retention": 0.06,
        "arpu_monthly_usd": 1.50,
        "average_ltv_usd": 10.00,
        "store_conversion_rate": 0.32,
    },
}

# Default benchmarks used when category is unknown
DEFAULT_CATEGORY = "utilities"

# Heuristic floor, not a statistically derived threshold: below this many raw
# impressions in the analysis window, "impressions aren't converting" (a CTR/
# creative problem) is the wrong diagnosis -- there's barely any reach to
# convert from at all, which is a keyword/title/subtitle targeting problem
# instead. See docs/growth_diagnostics_playbook.md §1a.
LOW_REACH_IMPRESSION_FLOOR = 1000

LOW_REACH_INSIGHT = (
    "Raw impression volume is very low (under {floor:,}) -- this isn't a "
    "conversion-rate problem, it's a reach problem: the title/subtitle/"
    "keyword field aren't indexing for enough real search volume. Fix "
    "targeting (aso-keyword get_keyword_volume/get_competitor_keywords), "
    "not screenshots. See docs/growth_diagnostics_playbook.md §1a."
)

# =============================================================================
# Insight Templates
# =============================================================================

LEAK_INSIGHTS: dict[str, str] = {
    "Impression → Store View": (
        "Icon/title aren't converting an impression into a tap. This is a "
        "creative problem, not a targeting problem -- test icon and title, "
        "not keywords. (If raw impression volume itself is low rather than "
        "just this ratio, that's the opposite diagnosis: a keyword/subtitle "
        "targeting gap. See docs/growth_diagnostics_playbook.md §1.)"
    ),
    "Store View → Install": (
        "People are viewing the listing and not installing -- screenshots, "
        "description, preview video, and star rating are the levers here, "
        "not keywords or title. Compare against category-leading listings "
        "(Mobbin) before proposing a specific creative change. "
        "See docs/growth_diagnostics_playbook.md §1b/§3."
    ),
    "Install → Day 1 Active": (
        "Users install but don't open the app on Day 1. "
        "Consider push notification onboarding or a stronger first-launch experience."
    ),
    "Day 1 → Onboarding Complete": (
        "Users drop off during onboarding. "
        "Consider simplifying onboarding steps, reducing permission requests, "
        "or adding a skip option."
    ),
    "Onboarding → Paywall View": (
        "Users complete onboarding but don't reach the paywall. "
        "Consider showing pricing earlier or improving engagement before the paywall."
    ),
    "Paywall View → Trial Start": (
        "Paywall conversion is below benchmark. Compare the live paywall "
        "against category-leading competitors (Mobbin search_screens/"
        "search_flows) on value-prop clarity, social proof, and plan/trial "
        "framing before proposing a specific change -- see "
        "docs/growth_diagnostics_playbook.md §2. Note: paywall_variant "
        "experiments have no automated rollback in this codebase; any "
        "change here stays manual-only."
    ),
    "Trial Start → Paid Conversion": (
        "Trial-to-paid conversion needs improvement. "
        "Consider better trial engagement emails, in-app reminders, "
        "or extending the trial for engaged users."
    ),
    "Install → Day 7 Retained": (
        "Week 1 retention is below average. "
        "Focus on delivering core value in the first 7 days. "
        "Consider streak mechanics or engagement hooks."
    ),
    "Install → Day 30 Retained": (
        "Monthly retention needs attention. "
        "Consider habit-forming features, content updates, "
        "or re-engagement campaigns for churning users."
    ),
}

# Map of transition names to their benchmark keys
TRANSITION_BENCHMARK_KEYS: dict[str, str] = {
    "Impression → Store View": "impression_to_store_view",
    "Store View → Install": "store_view_to_install",
    "Install → Day 1 Active": "install_to_d1_active",
    "Day 1 → Onboarding Complete": "d1_to_onboarding_complete",
    "Onboarding → Paywall View": "onboarding_to_paywall_view",
    "Paywall View → Trial Start": "paywall_to_trial_start",
    "Trial Start → Paid Conversion": "trial_to_paid",
    "Install → Day 7 Retained": "d7_retention",
    "Install → Day 30 Retained": "d30_retention",
}


def get_benchmarks(category: str) -> CategoryBenchmarks:
    """Get benchmark data for a category, falling back to defaults.

    Args:
        category: App category name (case-insensitive, underscores for spaces).

    Returns:
        Benchmark dictionary for the category.
    """
    key = category.lower().replace(" ", "_").replace("-", "_")
    return BENCHMARKS.get(key, BENCHMARKS[DEFAULT_CATEGORY])


def get_benchmark_for_transition(category: str, transition_name: str) -> float | None:
    """Get the benchmark rate for a specific funnel transition.

    Args:
        category: App category.
        transition_name: Funnel transition name (e.g., 'Store View → Install').

    Returns:
        Benchmark rate as a decimal, or None if not found.
    """
    benchmarks = get_benchmarks(category)
    key = TRANSITION_BENCHMARK_KEYS.get(transition_name)
    if key is None:
        return None
    return benchmarks.get(key)


def get_ltv(category: str) -> float:
    """Get the average LTV for a category.

    Args:
        category: App category.

    Returns:
        Average LTV in USD.
    """
    benchmarks = get_benchmarks(category)
    return benchmarks.get("average_ltv_usd", 12.0)


def list_categories() -> list[str]:
    """List all available benchmark categories."""
    return sorted(BENCHMARKS.keys())


def get_category_summary(category: str) -> dict[str, Any]:
    """Get a summary of benchmarks for a category.

    Args:
        category: App category.

    Returns:
        Dict with category name and key benchmark values.
    """
    benchmarks = get_benchmarks(category)
    return {
        "category": category,
        "store_conversion": f"{benchmarks.get('store_conversion_rate', 0):.0%}",
        "d1_retention": f"{benchmarks.get('d1_retention', 0):.0%}",
        "d7_retention": f"{benchmarks.get('d7_retention', 0):.0%}",
        "d30_retention": f"{benchmarks.get('d30_retention', 0):.0%}",
        "trial_to_paid": f"{benchmarks.get('trial_to_paid', 0):.0%}",
        "average_ltv_usd": f"${benchmarks.get('average_ltv_usd', 0):.2f}",
        "arpu_monthly_usd": f"${benchmarks.get('arpu_monthly_usd', 0):.2f}",
    }
