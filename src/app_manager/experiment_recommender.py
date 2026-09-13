"""Deterministic experiment designs derived from observed MCP funnel evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ExperimentRecommendationRequest(BaseModel):
    """Controls for ranking experiment designs from available evidence."""

    model_config = ConfigDict(extra="forbid")

    focus: str = Field(
        default="auto", pattern=r"^(auto|acquisition|activation|monetization|retention)$"
    )
    max_results: int = Field(default=3, ge=1, le=5)
    refresh_live: bool = False


STAGE_DESIGNS: dict[str, tuple[dict[str, Any], ...]] = {
    "Impression → Store View": (
        {
            "experiment_type": "store_creative",
            "label": "Store creative",
            "focus": "acquisition",
            "metric": "impression_to_store_view_rate",
            "treatment": "Replace the weakest icon, screenshot, or feature graphic with one focused on the primary user outcome.",
            "guardrails": ["store_view_to_install_rate", "rating_change", "organic_install_volume"],
        },
        {
            "experiment_type": "aso_metadata",
            "label": "Play Store metadata",
            "focus": "acquisition",
            "metric": "impression_to_store_view_rate",
            "treatment": "Rewrite the title and short description around the highest-intent rulebook keywords.",
            "guardrails": ["store_view_to_install_rate", "keyword_rank", "rating_change"],
        },
    ),
    "Store View → Install": (
        {
            "experiment_type": "aso_metadata",
            "label": "Play Store metadata",
            "focus": "acquisition",
            "metric": "store_view_to_install_rate",
            "treatment": "Test a clearer value proposition in the title and short description while preserving rulebook requirements.",
            "guardrails": ["store_listing_visitors", "organic_install_volume", "rating_change"],
        },
        {
            "experiment_type": "store_creative",
            "label": "Store creative",
            "focus": "acquisition",
            "metric": "store_view_to_install_rate",
            "treatment": "Reorder screenshots so the first three communicate outcome, proof, and ease of use.",
            "guardrails": ["store_listing_visitors", "organic_install_volume", "rating_change"],
        },
    ),
    "Install → Day 1 Active": (
        {
            "experiment_type": "remote_config",
            "label": "Remote configuration",
            "focus": "activation",
            "metric": "install_to_d1_active_rate",
            "treatment": "Reduce first-session friction by simplifying the initial path to the app's core value moment.",
            "guardrails": ["crash_rate", "anr_rate", "onboarding_completion_rate"],
        },
    ),
    "Day 1 → Onboarding Complete": (
        {
            "experiment_type": "remote_config",
            "label": "Remote configuration",
            "focus": "activation",
            "metric": "d1_to_onboarding_complete_rate",
            "treatment": "Shorten onboarding or defer nonessential permissions until after the first successful outcome.",
            "guardrails": ["crash_rate", "permission_denial_rate", "d1_retention"],
        },
    ),
    "Onboarding → Paywall View": (
        {
            "experiment_type": "paywall_variant",
            "label": "Paywall variant",
            "focus": "monetization",
            "metric": "onboarding_to_paywall_view_rate",
            "treatment": "Test paywall timing after a completed value moment instead of before the user experiences the core benefit.",
            "guardrails": ["onboarding_completion_rate", "d1_retention", "paywall_dismissal_rate"],
        },
    ),
    "Paywall View → Trial Start": (
        {
            "experiment_type": "paywall_variant",
            "label": "Paywall variant",
            "focus": "monetization",
            "metric": "paywall_to_trial_start_rate",
            "treatment": "Test a benefit-led paywall with clearer trial terms and one prominent recommended package.",
            "guardrails": ["paywall_dismissal_rate", "refund_rate", "d7_retention"],
        },
        {
            "experiment_type": "pricing_experiment",
            "label": "Pricing",
            "focus": "monetization",
            "metric": "paywall_to_trial_start_rate",
            "treatment": "Test one alternative trial or localized price point while keeping product value and placement unchanged.",
            "guardrails": ["revenue_per_payer", "refund_rate", "trial_to_paid_conversion_rate"],
        },
    ),
    "Trial Start → Paid Conversion": (
        {
            "experiment_type": "paywall_variant",
            "label": "Paywall variant",
            "focus": "monetization",
            "metric": "trial_to_paid_conversion_rate",
            "treatment": "Test trial education and renewal reminders without changing acquisition or price simultaneously.",
            "guardrails": ["refund_rate", "cancellation_rate", "support_contact_rate"],
        },
        {
            "experiment_type": "pricing_experiment",
            "label": "Pricing",
            "focus": "monetization",
            "metric": "trial_to_paid_conversion_rate",
            "treatment": "Test one package or localized price change while holding paywall copy and timing constant.",
            "guardrails": ["revenue_per_payer", "refund_rate", "cancellation_rate"],
        },
    ),
    "Install → Day 7 Retained": (
        {
            "experiment_type": "push_campaign",
            "label": "Push campaign",
            "focus": "retention",
            "metric": "d7_retention_rate",
            "treatment": "Send one behavior-triggered reminder tied to an unfinished high-value task during the first week.",
            "guardrails": ["notification_opt_out_rate", "uninstall_rate", "session_quality"],
        },
        {
            "experiment_type": "remote_config",
            "label": "Remote configuration",
            "focus": "retention",
            "metric": "d7_retention_rate",
            "treatment": "Expose a repeat-use shortcut or saved-state reminder after the first successful session.",
            "guardrails": ["crash_rate", "d1_retention", "core_action_completion_rate"],
        },
    ),
    "Install → Day 30 Retained": (
        {
            "experiment_type": "push_campaign",
            "label": "Push campaign",
            "focus": "retention",
            "metric": "d30_retention_rate",
            "treatment": "Test a lifecycle message based on prior successful behavior rather than a generic scheduled notification.",
            "guardrails": ["notification_opt_out_rate", "uninstall_rate", "d7_retention"],
        },
        {
            "experiment_type": "remote_config",
            "label": "Remote configuration",
            "focus": "retention",
            "metric": "d30_retention_rate",
            "treatment": "Test a returning-user surface that restores context and makes the next valuable action obvious.",
            "guardrails": ["crash_rate", "d7_retention", "session_quality"],
        },
    ),
}


def _is_fresh(captured_at: str | None, *, max_age_hours: int = 36) -> bool:
    if not captured_at:
        return False
    try:
        captured = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=UTC)
    return (datetime.now(UTC) - captured.astimezone(UTC)).total_seconds() <= max_age_hours * 3600


def recommend_experiment_designs(
    *,
    package_name: str,
    funnel: dict[str, Any],
    captured_at: str | None,
    focus: str = "auto",
    max_results: int = 3,
    active_experiment_types: set[str] | None = None,
) -> dict[str, Any]:
    """Rank complete experiment designs from observed, below-benchmark funnel stages."""
    active_types = active_experiment_types or set()
    data_sources = [str(source) for source in funnel.get("data_sources", [])]
    recommendations: list[dict[str, Any]] = []
    for leak in funnel.get("leaks", []):
        if not isinstance(leak, dict) or not leak.get("has_data"):
            continue
        stage = str(leak.get("name") or "")
        actual = leak.get("conversion_rate")
        benchmark = leak.get("benchmark_rate")
        gap = leak.get("gap")
        if not isinstance(actual, (int, float)) or not isinstance(benchmark, (int, float)):
            continue
        if not isinstance(gap, (int, float)) or gap >= 0:
            continue
        for design in STAGE_DESIGNS.get(stage, ()):
            if focus != "auto" and design["focus"] != focus:
                continue
            experiment_type = str(design["experiment_type"])
            target_improvement = min(
                0.20, max(0.05, abs(float(gap)) / max(float(actual), 0.01) / 2)
            )
            impact = float(leak.get("monthly_revenue_impact") or 0.0)
            hypothesis = (
                f"{design['label']} treatment will improve {stage} from {float(actual):.1%} "
                f"toward the {float(benchmark):.1%} benchmark by at least {target_improvement:.1%}."
            )
            recommendations.append(
                {
                    "id": f"{package_name}:{stage}:{experiment_type}",
                    "rank": 0,
                    "app_package": package_name,
                    "experiment_type": experiment_type,
                    "label": design["label"],
                    "focus": design["focus"],
                    "hypothesis": hypothesis,
                    "rationale": leak.get("insight") or f"{stage} is below its category benchmark.",
                    "success_metric": design["metric"],
                    "suggested_min_observation_days": 7,
                    "suggested_max_observation_days": 28,
                    "target_improvement_pct": target_improvement,
                    "estimated_monthly_impact": impact,
                    "conflicts_with_active_experiment": experiment_type in active_types,
                    "capability": "executable"
                    if experiment_type == "aso_metadata"
                    else "planning_only",
                    "design": {
                        "method": "before_after",
                        "control": "Current production experience during the frozen baseline period.",
                        "treatment": design["treatment"],
                        "primary_metric": design["metric"],
                        "guardrail_metrics": design["guardrails"],
                        "analysis_plan": (
                            "Freeze a complete baseline, change one variable group, collect non-overlapping "
                            "treatment periods, and compare persisted numerator/denominator evidence."
                        ),
                        "sample_guidance": "Do not conclude before minimum duration and source-specific sample gates are met.",
                    },
                    "evidence": {
                        "stage": stage,
                        "actual_rate": float(actual),
                        "benchmark_rate": float(benchmark),
                        "gap": float(gap),
                        "users_entered": leak.get("users_entered"),
                        "users_completed": leak.get("users_completed"),
                        "estimated_monthly_impact": impact,
                        "priority": leak.get("priority"),
                        "sources": data_sources,
                        "captured_at": captured_at,
                        "freshness": "fresh" if _is_fresh(captured_at) else "stale",
                    },
                }
            )

    recommendations.sort(
        key=lambda item: (
            item["conflicts_with_active_experiment"],
            -item["estimated_monthly_impact"],
            0 if item["capability"] == "executable" else 1,
        )
    )
    selected = recommendations[:max_results]
    for rank, recommendation in enumerate(selected, 1):
        recommendation["rank"] = rank
    return {
        "app_package": package_name,
        "generated_at": datetime.now(UTC).isoformat(),
        "source_status": "fresh" if _is_fresh(captured_at) else "stale",
        "data_sources": data_sources,
        "recommendations": selected,
    }
