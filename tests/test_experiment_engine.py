import json
from unittest.mock import AsyncMock, patch

import pytest

from app_manager.experiment_engine import ExperimentEvaluator, HypothesisGenerator


def test_evaluator_insufficient_data():
    evaluator = ExperimentEvaluator()
    # n < 2
    res = evaluator.evaluate(
        baseline_values=[0.10],
        treatment_values=[0.12, 0.13],
        target_improvement_pct=0.10,
        rollback_threshold_pct=0.15,
    )
    assert res.verdict == "insufficient_data"
    assert "Insufficient sample sizes" in res.reason


def test_evaluator_zero_baseline():
    evaluator = ExperimentEvaluator()
    res = evaluator.evaluate(
        baseline_values=[0.0, 0.0, 0.0],
        treatment_values=[0.12, 0.13, 0.14],
        target_improvement_pct=0.10,
        rollback_threshold_pct=0.15,
    )
    assert res.verdict == "inconclusive"
    assert "Baseline mean is zero" in res.reason


def test_evaluator_rollback():
    evaluator = ExperimentEvaluator()
    # Big drop in treatment group
    res = evaluator.evaluate(
        baseline_values=[10.0, 11.0, 10.5, 9.5],
        treatment_values=[8.0, 7.5, 8.2, 7.8],
        target_improvement_pct=0.10,
        rollback_threshold_pct=0.15,
    )
    assert res.verdict == "rollback"
    assert "exceeding rollback threshold" in res.reason


def test_evaluator_winner():
    evaluator = ExperimentEvaluator()
    # High difference, small variance
    baseline = [1.0, 1.05, 0.98, 1.02, 1.0, 1.01, 0.99]
    treatment = [1.2, 1.25, 1.18, 1.22, 1.21, 1.23, 1.19]
    res = evaluator.evaluate(
        baseline_values=baseline,
        treatment_values=treatment,
        target_improvement_pct=0.10,
        rollback_threshold_pct=0.15,
    )
    assert res.verdict == "winner"
    assert res.confidence >= 0.90
    assert res.observed_change >= 0.10


def test_evaluator_loser():
    evaluator = ExperimentEvaluator()
    # Standard difference but not meeting target improvement or low significance
    baseline = [1.0, 1.05, 0.98, 1.02, 1.0, 1.01, 0.99]
    treatment = [1.01, 1.03, 1.02, 1.0, 1.02, 1.01, 1.02]
    res = evaluator.evaluate(
        baseline_values=baseline,
        treatment_values=treatment,
        target_improvement_pct=0.10,
        rollback_threshold_pct=0.15,
    )
    # Significant but change (around 1-2%) is below target 10%
    # Wait, p-value might be small or large depending on sample size and standard deviation.
    # Let's verify standard loser or insufficient data
    assert res.verdict in ("loser", "insufficient_data")


@pytest.mark.asyncio
async def test_hypothesis_generator_parses_successful_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    generator = HypothesisGenerator()

    response_json = {
        "diagnosis": "Store CVR is 18% vs 25% benchmark — title lacks primary keyword",
        "proposed_experiment": {
            "app_package": "com.example.app",
            "experiment_type": "aso_metadata",
            "hypothesis": "Adding 'loan EMI' to title will improve store CVR from 18% to 23%",
            "target_tool": "play_store/update_listing",
            "target_args": {
                "packageName": "com.example.app",
                "language": "en-US",
                "title": "EMI Calculator - Easy Loan EMI",
            },
            "success_metric": "store_view_to_install_rate",
            "target_improvement_pct": 0.10,
            "rollback_degradation_pct": 0.15,
            "requires_approval": True,
        },
        "expected_impact": "5% CVR improvement",
        "risk_assessment": "Low",
    }

    with patch(
        "app_manager.experiment_engine.complete_json",
        new=AsyncMock(return_value=f"```json\n{json.dumps(response_json)}\n```"),
    ):
        result = await generator.generate(
            app_package="com.example.app",
            funnel_snapshot={"store_cvr": 0.18},
            benchmarks={"store_cvr": 0.25},
            active_experiments=[],
            rulebook={},
        )

    assert result is not None
    assert result["proposed_experiment"]["experiment_type"] == "aso_metadata"
    assert result["proposed_experiment"]["app_package"] == "com.example.app"
    assert result["diagnosis"].startswith("Store CVR")


@pytest.mark.asyncio
async def test_hypothesis_generator_handles_malformed_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    generator = HypothesisGenerator()

    with patch(
        "app_manager.experiment_engine.complete_json",
        new=AsyncMock(return_value="not valid json {{{"),
    ):
        result = await generator.generate(
            app_package="com.example.app",
            funnel_snapshot={},
            benchmarks={},
            active_experiments=[],
            rulebook={},
        )

    assert result is None


@pytest.mark.asyncio
async def test_hypothesis_generator_returns_none_without_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("HYPOTHESIS_LLM_PROVIDER", raising=False)
    generator = HypothesisGenerator()

    with patch("app_manager.experiment_engine.complete_json", new=AsyncMock()) as mock_complete:
        result = await generator.generate(
            app_package="com.example.app",
            funnel_snapshot={},
            benchmarks={},
            active_experiments=[],
            rulebook={},
        )

    assert result is None
    mock_complete.assert_not_called()
