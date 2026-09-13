"""Orchestration engine for experiment lifecycle management and statistical evaluation."""

from __future__ import annotations

import json
import math
import os
import re
from enum import Enum
from typing import Any, cast

import structlog
from pydantic import BaseModel, Field

from app_manager.llm_provider import complete_json

logger = structlog.get_logger(__name__)


class ExperimentType(str, Enum):
    ASO_METADATA = "aso_metadata"  # Title/description/keyword changes
    ASO_CREATIVES = "aso_creatives"  # Screenshots, feature graphic
    PAYWALL_VARIANT = "paywall_variant"  # Different offering/price/trial
    AD_UNIT_CONFIG = "ad_unit_config"  # Ad placement, format, frequency
    PUSH_CAMPAIGN = "push_campaign"  # Re-engagement notification test
    UA_BUDGET = "ua_budget"  # Paid campaign budget shifts
    REMOTE_CONFIG = "remote_config"  # Feature flag / pricing parity


class ExperimentStatus(str, Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    ACTIVE = "active"
    MEASURING = "measuring"
    CONCLUDED = "concluded"
    ROLLED_BACK = "rolled_back"


class ExperimentSpec(BaseModel):
    app_package: str
    experiment_type: ExperimentType
    hypothesis: str
    target_tool: str
    target_args: dict
    success_metric: str
    baseline_window_days: int = 7
    min_observation_days: int = 7
    max_observation_days: int = 28
    target_improvement_pct: float
    rollback_degradation_pct: float = 0.15
    requires_approval: bool = True
    max_concurrent_per_app: int = 2
    incompatible_with: list[ExperimentType] = Field(default_factory=list)


class EvaluationResult(BaseModel):
    verdict: str  # "winner" | "loser" | "inconclusive" | "rollback" | "insufficient_data"
    confidence: float
    observed_change: float
    reason: str | None = None


# Pure Python Student's t distribution helpers for Welch's t-test p-value calculation
def _student_t_pdf(x: float, df: float) -> float:
    """Compute the probability density function (PDF) of Student's t-distribution."""
    try:
        c = math.gamma((df + 1) / 2) / (math.sqrt(df * math.pi) * math.gamma(df / 2))
        return cast("float", c * (1 + (x**2) / df) ** (-(df + 1) / 2))
    except (ValueError, OverflowError):
        # Fallback approximation for large degrees of freedom (Normal distribution)
        return (1 / math.sqrt(2 * math.pi)) * math.exp(-0.5 * x**2)


def _student_t_cdf(t: float, df: float) -> float:
    """Compute the cumulative distribution function (CDF) of Student's t-distribution using numerical integration."""
    t_abs = abs(t)
    steps = 1000
    h = t_abs / steps

    # Trapezoidal rule integration from 0 to |t|
    area = 0.5 * (_student_t_pdf(0, df) + _student_t_pdf(t_abs, df))
    for i in range(1, steps):
        area += _student_t_pdf(i * h, df)

    res = 0.5 + area * h
    # Clamp to [0.5, 1.0] for safety
    res = max(0.5, min(1.0, res))
    return res if t >= 0 else 1.0 - res


class ExperimentEvaluator:
    """Evaluates whether an experiment has reached a conclusive result using Welch's t-test."""

    def evaluate(
        self,
        baseline_values: list[float],
        treatment_values: list[float],
        target_improvement_pct: float,
        rollback_threshold_pct: float,
    ) -> EvaluationResult:
        """Evaluate before/after metric series using Welch's t-test with a 90% confidence threshold."""
        n1 = len(baseline_values)
        n2 = len(treatment_values)

        if n1 < 2 or n2 < 2:
            return EvaluationResult(
                verdict="insufficient_data",
                confidence=0.0,
                observed_change=0.0,
                reason=f"Insufficient sample sizes: baseline n={n1}, treatment n={n2} (minimum 2 required).",
            )

        mean1 = sum(baseline_values) / n1
        mean2 = sum(treatment_values) / n2

        if mean1 == 0:
            return EvaluationResult(
                verdict="inconclusive",
                confidence=0.0,
                observed_change=0.0,
                reason="Baseline mean is zero. Cannot evaluate percentage change.",
            )

        observed_change = (mean2 - mean1) / mean1

        # Check for degradation (emergency rollback threshold)
        if observed_change < -rollback_threshold_pct:
            return EvaluationResult(
                verdict="rollback",
                confidence=1.0,
                observed_change=observed_change,
                reason=f"Metric degraded by {observed_change:.1%}, exceeding rollback threshold of -{rollback_threshold_pct:.1%}.",
            )

        var1 = sum((x - mean1) ** 2 for x in baseline_values) / (n1 - 1)
        var2 = sum((x - mean2) ** 2 for x in treatment_values) / (n2 - 1)

        # Handle zero variance edge cases
        if var1 == 0 and var2 == 0:
            if mean2 > mean1:
                return EvaluationResult(
                    verdict="winner", confidence=1.0, observed_change=observed_change
                )
            elif mean2 < mean1:
                return EvaluationResult(
                    verdict="loser", confidence=1.0, observed_change=observed_change
                )
            else:
                return EvaluationResult(
                    verdict="inconclusive", confidence=1.0, observed_change=observed_change
                )

        # Welch's t-test statistic
        se = math.sqrt((var1 / n1) + (var2 / n2))
        t_stat = (mean2 - mean1) / se

        # Welch-Satterthwaite formula for degrees of freedom
        num = ((var1 / n1) + (var2 / n2)) ** 2
        den = (((var1 / n1) ** 2) / (n1 - 1)) + (((var2 / n2) ** 2) / (n2 - 1))
        df = num / den if den > 0 else 1.0

        # Calculate p-value (two-tailed test)
        p_value = 2.0 * (1.0 - _student_t_cdf(abs(t_stat), df))
        confidence = 1.0 - p_value
        confidence = max(0.0, min(1.0, confidence))

        logger.info(
            "Welch's t-test evaluated",
            baseline_n=n1,
            treatment_n=n2,
            baseline_mean=mean1,
            treatment_mean=mean2,
            t_stat=t_stat,
            df=df,
            p_value=p_value,
            confidence=confidence,
            observed_change=observed_change,
        )

        if confidence >= 0.90:  # 90% confidence threshold
            if observed_change >= target_improvement_pct:
                return EvaluationResult(
                    verdict="winner",
                    confidence=confidence,
                    observed_change=observed_change,
                    reason=f"Significant improvement of {observed_change:.1%} (target {target_improvement_pct:.1%}) at {confidence:.1%} confidence.",
                )
            else:
                return EvaluationResult(
                    verdict="loser",
                    confidence=confidence,
                    observed_change=observed_change,
                    reason=f"No significant improvement (observed {observed_change:.1%}, target {target_improvement_pct:.1%}) at {confidence:.1%} confidence.",
                )

        return EvaluationResult(
            verdict="insufficient_data",
            confidence=confidence,
            observed_change=observed_change,
            reason=f"Result not statistically significant (confidence {confidence:.1%}, required 90%).",
        )


class HypothesisGenerator:
    """Generates optimized experiment hypotheses via LLM based on funnel performance and benchmarks."""

    def __init__(self, api_key: str | None = None, provider: str | None = None) -> None:
        self.provider = (provider or os.environ.get("HYPOTHESIS_LLM_PROVIDER", "gemini")).lower()

        resolved_key: str | None
        if api_key:
            resolved_key = api_key
        elif self.provider == "anthropic":
            resolved_key = os.environ.get("ANTHROPIC_API_KEY")
        elif self.provider == "openai":
            resolved_key = os.environ.get("OPENAI_API_KEY")
        else:
            # "gemini", or any unrecognized provider, falls back to Gemini's key.
            resolved_key = os.environ.get("GEMINI_API_KEY")
        self.api_key = resolved_key

    async def generate(
        self,
        app_package: str,
        funnel_snapshot: dict[str, Any],
        benchmarks: dict[str, Any],
        active_experiments: list[dict[str, Any]],
        rulebook: dict[str, Any],
        trust_tier: str = "conservative",
    ) -> dict[str, Any] | None:
        """Propose a new experiment based on rulebook, benchmarks, and active experiments."""
        if not self.api_key:
            logger.warning(
                "No LLM API key configured. Skipping hypothesis generation.",
                provider=self.provider,
            )
            return None

        # Build prompt
        prompt = f"""You are the Experiment Strategist for the mobile app '{app_package}'.
Your task is to diagnose the biggest funnel leak and propose an experiment to fix it.

INPUT:
- Current funnel metrics: {json.dumps(funnel_snapshot)}
- Category benchmarks: {json.dumps(benchmarks)}
- Active running experiments: {json.dumps(active_experiments)}
- App rulebook constraints: {json.dumps(rulebook)}
- System trust tier: {trust_tier}

RULES:
1. Never propose an experiment that conflicts with a currently active one.
2. If trust_tier is 'conservative', only propose ASO metadata experiments (type 'aso_metadata').
3. If trust_tier is 'moderate', you may also propose paywall ('paywall_variant') and ad config ('ad_unit_config') experiments.
4. If trust_tier is 'aggressive', you may propose paid campaign budget shifts ('ua_budget') and push notifications ('push_campaign').
5. Identify the single funnel stage with the worst drop-off compared to the benchmark and suggest a high-leverage tool update.
6. The target_tool and target_args should correspond to valid MCP tools:
   - For 'aso_metadata': play_store/update_listing (arguments: packageName, language, title, shortDescription, fullDescription)
   - For 'paywall_variant': revenuecat/create_offering (arguments: project_id, offering_config)
   - For 'ad_unit_config': play_store/deploy_app with ad config changes or similar

Format the response strictly as a JSON object matching this schema:
{{
    "diagnosis": "Store CVR is 18% vs 25% benchmark — title lacks primary keyword",
    "proposed_experiment": {{
        "app_package": "{app_package}",
        "experiment_type": "aso_metadata",
        "hypothesis": "Adding 'loan EMI' to title will improve store CVR from 18% to 23%",
        "target_tool": "play_store/update_listing",
        "target_args": {{
            "packageName": "{app_package}",
            "language": "en-US",
            "title": "EMI Calculator - Easy Loan EMI"
        }},
        "success_metric": "store_view_to_install_rate",
        "target_improvement_pct": 0.10,
        "rollback_degradation_pct": 0.15,
        "requires_approval": true
    }},
    "expected_impact": "5% CVR improvement → ~200 additional installs/month",
    "risk_assessment": "Low — metadata change is instantly reversible"
}}
"""
        system_instructions = (
            "You are a JSON-only response agent. You must output valid, un-nested JSON "
            "matching the requested schema and nothing else."
        )

        try:
            res_text = await complete_json(
                system_instructions, prompt, provider=self.provider, api_key=self.api_key
            )
            res_text = res_text.strip()
            # Clean markdown backticks if returned
            if res_text.startswith("```"):
                res_text = re.sub(r"^```(?:json)?\n", "", res_text)
                res_text = re.sub(r"\n```$", "", res_text)

            parsed = cast("dict[str, Any]", json.loads(res_text))
            logger.info(
                "Hypothesis generated successfully",
                package=app_package,
                type=parsed.get("proposed_experiment", {}).get("experiment_type"),
            )
            return parsed
        except Exception as e:
            logger.exception("Failed to generate hypothesis", error=str(e))
            return None
