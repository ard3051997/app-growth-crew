"""Tests for the Pomodori-scoping and autonomous-rollback changes in run_autonomous_loop.py.

No real network, subprocess, or scheduler calls -- collaborators are mocked.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import run_autonomous_loop as loop_module
from run_autonomous_loop import (
    _apply_automatic_disposition,
    _autonomous_rollback_scope,
    _prime_telegram_offset,
    _scoped_apps,
    _stuck_active_note,
    collect_experiment_observations,
)


def _mock_httpx_client(get_response: MagicMock) -> MagicMock:
    """Build a mock httpx.AsyncClient usable as `async with httpx.AsyncClient() as client`."""
    client = AsyncMock()
    client.get = AsyncMock(return_value=get_response)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


APPS = [
    {"package_name": "com.pomodoro.krypt.timemanagement.focus.app", "display_name": "Pomodori"},
    {"package_name": "com.finance.loan.emicalculator", "display_name": "EMI Calculator"},
]


class TestScopedApps:
    def test_unset_env_var_returns_all_apps(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AUTONOMOUS_LOOP_PACKAGES", raising=False)
        assert _scoped_apps(APPS) == APPS

    def test_set_env_var_filters_to_named_packages(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(
            "AUTONOMOUS_LOOP_PACKAGES", "com.pomodoro.krypt.timemanagement.focus.app"
        )
        assert _scoped_apps(APPS) == [APPS[0]]

    def test_unknown_package_in_env_var_yields_empty_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AUTONOMOUS_LOOP_PACKAGES", "com.unknown.app")
        assert _scoped_apps(APPS) == []

    def test_multiple_packages_are_comma_separated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(
            "AUTONOMOUS_LOOP_PACKAGES",
            "com.pomodoro.krypt.timemanagement.focus.app, com.finance.loan.emicalculator",
        )
        assert _scoped_apps(APPS) == APPS


class TestAutonomousRollbackScope:
    def test_unset_env_var_is_an_empty_scope(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AUTONOMOUS_LOOP_PACKAGES", raising=False)
        assert _autonomous_rollback_scope() == frozenset()

    def test_set_env_var_returns_the_named_packages(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(
            "AUTONOMOUS_LOOP_PACKAGES", "com.pomodoro.krypt.timemanagement.focus.app"
        )
        assert _autonomous_rollback_scope() == {"com.pomodoro.krypt.timemanagement.focus.app"}


def _valid_auto_low_risk_bundle() -> tuple[dict, dict, dict]:
    experiment = {
        "id": "exp-1",
        "execution_mode": "auto_low_risk",
        "approved_via": "auto_low_risk",
    }
    validation = {"valid": True, "effective_execution_mode": "auto_low_risk"}
    evaluation = {"verdict": "winner", "reason": "great"}
    return experiment, evaluation, validation


class TestApplyAutomaticDisposition:
    @pytest.mark.asyncio
    async def test_winner_retain_still_requires_true_auto_low_risk(self) -> None:
        lifecycle = MagicMock()
        lifecycle.rollback = AsyncMock()
        experiment = {"id": "exp-1", "execution_mode": "manual", "approved_via": "manual"}
        evaluation = {"verdict": "winner", "reason": "great"}
        validation = {"valid": True, "effective_execution_mode": "manual"}

        await _apply_automatic_disposition(
            lifecycle, experiment, evaluation, validation, allow_manual_rollback=True
        )

        lifecycle.retain.assert_not_called()

    @pytest.mark.asyncio
    async def test_winner_retain_fires_for_true_auto_low_risk(self) -> None:
        lifecycle = MagicMock()
        experiment, evaluation, validation = _valid_auto_low_risk_bundle()

        await _apply_automatic_disposition(lifecycle, experiment, evaluation, validation)

        lifecycle.retain.assert_called_once()

    @pytest.mark.asyncio
    async def test_rollback_fires_for_manual_experiments_in_the_autonomous_scope(self) -> None:
        lifecycle = MagicMock()
        lifecycle.rollback = AsyncMock()
        experiment = {"id": "exp-1", "execution_mode": "manual", "approved_via": "manual"}
        evaluation = {"verdict": "rollback", "reason": "degraded"}
        validation = {"valid": True, "effective_execution_mode": "manual"}

        await _apply_automatic_disposition(
            lifecycle, experiment, evaluation, validation, allow_manual_rollback=True
        )

        lifecycle.rollback.assert_awaited_once_with(
            "exp-1", actor="scheduler", reason="Automatic rollback disposition: degraded"
        )

    @pytest.mark.asyncio
    async def test_rollback_does_not_fire_for_manual_experiments_outside_the_scope(self) -> None:
        """Apps not named in AUTONOMOUS_LOOP_PACKAGES keep today's behavior unchanged."""
        lifecycle = MagicMock()
        lifecycle.rollback = AsyncMock()
        experiment = {"id": "exp-1", "execution_mode": "manual", "approved_via": "manual"}
        evaluation = {"verdict": "rollback", "reason": "degraded"}
        validation = {"valid": True, "effective_execution_mode": "manual"}

        await _apply_automatic_disposition(
            lifecycle, experiment, evaluation, validation, allow_manual_rollback=False
        )

        lifecycle.rollback.assert_not_called()

    @pytest.mark.asyncio
    async def test_read_only_mode_takes_no_action(self) -> None:
        lifecycle = MagicMock()
        lifecycle.rollback = AsyncMock()
        experiment = {"id": "exp-1", "execution_mode": "manual", "approved_via": "manual"}
        evaluation = {"verdict": "rollback", "reason": "degraded"}
        validation = {"valid": True, "effective_execution_mode": "manual"}

        with patch("run_autonomous_loop.is_read_only", return_value=True):
            await _apply_automatic_disposition(
                lifecycle, experiment, evaluation, validation, allow_manual_rollback=True
            )

        lifecycle.rollback.assert_not_called()
        lifecycle.retain.assert_not_called()


class TestCollectExperimentObservationsKeywordRank:
    @pytest.mark.asyncio
    async def test_records_a_real_keyword_rank_observation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        package = "com.pomodoro.krypt.timemanagement.focus.app"
        experiment = {
            "id": "exp-rank-1",
            "app_package": package,
            "status": "measuring",
            "success_metric": "keyword_rank",
            "evidence_json": json.dumps(
                {"baseline": {"metric": "keyword_rank", "keyword": "pomodoro", "locale": "en-GB"}}
            ),
        }
        monkeypatch.setenv("AUTONOMOUS_LOOP_PACKAGES", package)
        monkeypatch.setattr(loop_module, "init_db", lambda *_a, **_k: None)
        monkeypatch.setattr(loop_module, "get_db_experiments", lambda *_a, **_k: [experiment])
        monkeypatch.setattr(
            loop_module,
            "get_apps_config",
            lambda: [{"package_name": package, "display_name": "Pomodori"}],
        )

        mock_lifecycle = MagicMock()
        monkeypatch.setattr(loop_module, "ExperimentLifecycle", lambda *_a, **_k: mock_lifecycle)

        mock_client = MagicMock()
        mock_client.get_keyword_rank.return_value = {
            "keyword": "pomodoro",
            "rank": 42,
            "total_results": 196,
            "country": "gb",
        }
        with patch("app_store_mcp.client.AppStoreClient", return_value=mock_client):
            await collect_experiment_observations()

        mock_client.get_keyword_rank.assert_called_once_with(package, "pomodoro", country="gb")
        mock_lifecycle.observe.assert_called_once()
        call_kwargs = mock_lifecycle.observe.call_args.kwargs
        assert call_kwargs["rank"] == 42
        assert call_kwargs["source"] == "app_store_search_api"

    @pytest.mark.asyncio
    async def test_apps_outside_the_scope_are_not_observed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        package = "com.pomodoro.krypt.timemanagement.focus.app"
        other_package = "com.finance.loan.emicalculator"
        experiment = {
            "id": "exp-rank-1",
            "app_package": package,
            "status": "measuring",
            "success_metric": "keyword_rank",
            "evidence_json": "{}",
        }
        monkeypatch.setenv("AUTONOMOUS_LOOP_PACKAGES", other_package)
        monkeypatch.setattr(loop_module, "init_db", lambda *_a, **_k: None)
        monkeypatch.setattr(loop_module, "get_db_experiments", lambda *_a, **_k: [experiment])
        monkeypatch.setattr(
            loop_module,
            "get_apps_config",
            lambda: [{"package_name": other_package, "display_name": "EMI Calculator"}],
        )
        mock_lifecycle = MagicMock()
        monkeypatch.setattr(loop_module, "ExperimentLifecycle", lambda *_a, **_k: mock_lifecycle)

        await collect_experiment_observations()

        mock_lifecycle.observe.assert_not_called()


class TestPrimeTelegramOffset:
    @pytest.mark.asyncio
    async def test_no_token_is_a_no_op(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        loop_module._telegram_offset = 0
        await _prime_telegram_offset()
        assert loop_module._telegram_offset == 0

    @pytest.mark.asyncio
    async def test_skips_past_existing_backlog(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token")
        loop_module._telegram_offset = 0
        response = MagicMock(status_code=200)
        response.json.return_value = {
            "ok": True,
            "result": [{"update_id": 100}, {"update_id": 102}, {"update_id": 101}],
        }
        with patch("httpx.AsyncClient", return_value=_mock_httpx_client(response)):
            await _prime_telegram_offset()

        assert loop_module._telegram_offset == 103

    @pytest.mark.asyncio
    async def test_empty_backlog_leaves_offset_at_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token")
        loop_module._telegram_offset = 0
        response = MagicMock(status_code=200)
        response.json.return_value = {"ok": True, "result": []}
        with patch("httpx.AsyncClient", return_value=_mock_httpx_client(response)):
            await _prime_telegram_offset()

        assert loop_module._telegram_offset == 0


class TestStuckActiveNote:
    def test_active_experiment_gets_an_explicit_warning(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            loop_module, "get_db_experiment", lambda *_a, **_k: {"status": "active"}
        )
        note = _stuck_active_note("exp-1")
        assert "cannot be retried automatically" in note

    def test_non_active_experiment_gets_no_note(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            loop_module, "get_db_experiment", lambda *_a, **_k: {"status": "approved"}
        )
        assert _stuck_active_note("exp-1") == ""

    def test_missing_experiment_gets_no_note(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(loop_module, "get_db_experiment", lambda *_a, **_k: None)
        assert _stuck_active_note("exp-1") == ""
