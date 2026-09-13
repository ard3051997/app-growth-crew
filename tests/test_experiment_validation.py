"""Tests for the executable-tool and executable-locale generalization in
experiment_validation, added to support App Store Connect apps alongside
Play Store apps."""

from __future__ import annotations

from datetime import UTC, datetime

from app_manager.experiment_validation import (
    EXECUTABLE_METRICS,
    EXECUTABLE_TOOLS,
    validate_experiment,
)

PACKAGE = "com.pomodoro.example"
NOW = datetime(2026, 8, 29, 12, tzinfo=UTC)


def _baseline(*, locale: str = "en-GB") -> dict:
    return {
        "baseline": {
            "metric": "store_view_to_install_rate",
            "locale": locale,
            "visitors": 10_000,
            "installs": 2_000,
            "measured_at": NOW.isoformat(),
            "source": "play_console_gcs_store_performance",
        }
    }


def _experiment(*, target_tool: str, language: str) -> dict:
    return {
        "id": "exp-1",
        "app_package": PACKAGE,
        "experiment_type": "aso_metadata",
        "target_tool": target_tool,
        "target_args": {
            "packageName": PACKAGE,
            "language": language,
            "title": "Pomodori",
        },
        "success_metric": "store_view_to_install_rate",
        "execution_mode": "auto_low_risk",
    }


def _rank_baseline(*, rank: int | None, locale: str = "en-GB") -> dict:
    return {
        "baseline": {
            "metric": "keyword_rank",
            "keyword": "pomodoro",
            "rank": rank,
            "locale": locale,
            "measured_at": NOW.isoformat(),
            "source": "app_store_search_api",
        }
    }


def _rank_experiment(*, language: str = "en-GB") -> dict:
    return {
        "id": "exp-2",
        "app_package": PACKAGE,
        "experiment_type": "aso_metadata",
        "target_tool": "app_store_connect/update_listing",
        "target_args": {
            "packageName": PACKAGE,
            "language": language,
            "title": "Pomodori - Pomodoro Timer",
        },
        "success_metric": "keyword_rank",
        "execution_mode": "manual",
    }


class TestExecutableTools:
    def test_play_store_update_listing_is_accepted(self) -> None:
        result = validate_experiment(
            _experiment(target_tool="play_store/update_listing", language="en-US"),
            evidence=_baseline(locale="en-US"),
            now=NOW,
        )
        assert "unsupported_golden_path" not in {e["code"] for e in result["errors"]}

    def test_app_store_connect_update_listing_is_accepted(self) -> None:
        result = validate_experiment(
            _experiment(target_tool="app_store_connect/update_listing", language="en-GB"),
            evidence=_baseline(locale="en-GB"),
            executable_locale="en-GB",
            now=NOW,
        )
        assert "unsupported_golden_path" not in {e["code"] for e in result["errors"]}
        assert result["valid"] is True

    def test_unknown_target_tool_is_rejected(self) -> None:
        result = validate_experiment(
            _experiment(target_tool="some_other_tool/update_listing", language="en-US"),
            evidence=_baseline(locale="en-US"),
            now=NOW,
        )
        assert "unsupported_golden_path" in {e["code"] for e in result["errors"]}

    def test_both_executable_tools_are_in_the_set(self) -> None:
        assert {"play_store/update_listing", "app_store_connect/update_listing"} == EXECUTABLE_TOOLS


class TestExecutableLocale:
    def test_defaults_to_en_us(self) -> None:
        result = validate_experiment(
            _experiment(target_tool="play_store/update_listing", language="en-GB"),
            evidence=_baseline(locale="en-GB"),
            now=NOW,
        )
        assert any(e["code"] == "unsupported_locale" for e in result["errors"])

    def test_app_with_a_non_default_locale_rejects_en_us(self) -> None:
        """Pomodori's real listing locale is en-GB -- en-US must not validate for it."""
        result = validate_experiment(
            _experiment(target_tool="app_store_connect/update_listing", language="en-US"),
            evidence=_baseline(locale="en-US"),
            executable_locale="en-GB",
            now=NOW,
        )
        assert any(e["code"] == "unsupported_locale" for e in result["errors"])

    def test_baseline_locale_must_match_executable_locale(self) -> None:
        result = validate_experiment(
            _experiment(target_tool="app_store_connect/update_listing", language="en-GB"),
            evidence=_baseline(locale="en-US"),
            executable_locale="en-GB",
            now=NOW,
        )
        assert any(e["code"] == "baseline_locale_mismatch" for e in result["errors"])


class TestKeywordRankMetric:
    """A brand-new app with too little install volume for a conversion-rate
    baseline can use a real App Store search rank instead."""

    def test_both_metrics_are_executable(self) -> None:
        assert {"store_view_to_install_rate", "keyword_rank"} == EXECUTABLE_METRICS

    def test_not_ranked_is_a_valid_baseline(self) -> None:
        """rank=None means 'not currently ranked' -- a real, valid starting point."""
        result = validate_experiment(
            _rank_experiment(),
            evidence=_rank_baseline(rank=None),
            executable_locale="en-GB",
            now=NOW,
        )
        assert result["valid"] is True
        assert result["errors"] == []

    def test_a_measured_rank_is_a_valid_baseline(self) -> None:
        result = validate_experiment(
            _rank_experiment(),
            evidence=_rank_baseline(rank=138),
            executable_locale="en-GB",
            now=NOW,
        )
        assert result["valid"] is True

    def test_missing_keyword_is_rejected(self) -> None:
        baseline = _rank_baseline(rank=None)
        del baseline["baseline"]["keyword"]
        result = validate_experiment(
            _rank_experiment(), evidence=baseline, executable_locale="en-GB", now=NOW
        )
        assert any(e["code"] == "invalid_baseline_counts" for e in result["errors"])

    def test_zero_or_negative_rank_is_rejected(self) -> None:
        result = validate_experiment(
            _rank_experiment(),
            evidence=_rank_baseline(rank=0),
            executable_locale="en-GB",
            now=NOW,
        )
        assert any(e["code"] == "invalid_baseline_counts" for e in result["errors"])

    def test_conversion_rate_experiment_still_requires_visitors_and_installs(self) -> None:
        """The generalization must not loosen validation for the original metric."""
        baseline = _rank_baseline(rank=None)
        baseline["baseline"]["metric"] = "store_view_to_install_rate"
        result = validate_experiment(
            _experiment(target_tool="app_store_connect/update_listing", language="en-GB"),
            evidence=baseline,
            executable_locale="en-GB",
            now=NOW,
        )
        assert any(e["code"] == "invalid_baseline_counts" for e in result["errors"])
