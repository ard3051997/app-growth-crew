"""Authoritative experiment lifecycle shared by HTTP handlers and the scheduler."""

from __future__ import annotations

import inspect
import json
import math
import os
import uuid
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from datetime import date as calendar_date
from pathlib import Path
from typing import Any

import yaml

from app_manager import store_listing_client
from app_manager.experiment_validation import (
    EXECUTABLE_LOCALE,
    EXECUTABLE_TOOLS,
    KEYWORD_RANK_METRIC,
    validate_experiment,
)
from funnel_engine.db import (
    DEFAULT_DB_PATH,
    create_db_experiment,
    get_db_actions,
    get_db_experiment,
    get_db_experiments,
    get_db_observations,
    insert_db_observation_if_non_overlapping,
    is_emergency_brake_active,
    log_db_action,
    update_db_experiment_fields,
)
from mcp_gc_shared.write_guard import WriteBlockedError, assert_writes_allowed

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
# Deliberately larger than any real App Store search result rank (get_keyword_rank
# is called with limit<=200), so "not found in search results" always sorts as
# strictly worse than any real rank in threshold comparisons.
RANK_NOT_FOUND_SENTINEL = 100_000.0
JsonDict = dict[str, Any]
AsyncOrSync = Callable[..., Any | Awaitable[Any]]


class LifecycleError(RuntimeError):
    """Base error for a rejected lifecycle operation."""


class ExperimentNotFoundError(LifecycleError):
    """Raised when an experiment identifier does not exist."""


class LifecycleConflictError(LifecycleError):
    """Raised when state or policy prevents an operation."""


class PostWriteBookkeepingError(LifecycleError):
    """Raised when a remote write succeeded but local finalization did not."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _json_object(value: Any) -> JsonDict:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _as_dict(value: Any) -> JsonDict:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        return dumped if isinstance(dumped, dict) else {"value": dumped}
    return {"value": value}


def _successful(value: Any) -> bool:
    if isinstance(value, dict):
        return value.get("success") is True
    return getattr(value, "success", None) is True


async def _call(function: AsyncOrSync, *args: Any) -> Any:
    result = function(*args)
    return await result if inspect.isawaitable(result) else result


def evaluate_two_proportion_conversion(
    *,
    baseline_visitors: int,
    baseline_installs: int,
    treatment_visitors: int,
    treatment_installs: int,
    target_improvement_pct: float,
    rollback_degradation_pct: float,
    confidence_threshold: float = 0.90,
) -> JsonDict:
    """Evaluate conversion counts with a pooled two-proportion z-test."""
    counts = (baseline_visitors, baseline_installs, treatment_visitors, treatment_installs)
    if (
        any(isinstance(value, bool) or not isinstance(value, int) for value in counts)
        or baseline_visitors <= 0
        or treatment_visitors <= 0
        or not 0 <= baseline_installs <= baseline_visitors
        or not 0 <= treatment_installs <= treatment_visitors
    ):
        return {
            "verdict": "insufficient_data",
            "confidence": 0.0,
            "observed_change": 0.0,
            "baseline_rate": None,
            "treatment_rate": None,
            "reason": "Valid baseline and treatment visitor/install counts are required.",
            "method": "two_proportion_z_test",
        }

    baseline_rate = baseline_installs / baseline_visitors
    treatment_rate = treatment_installs / treatment_visitors
    if baseline_rate == 0:
        return {
            "verdict": "inconclusive",
            "confidence": 0.0,
            "observed_change": 0.0,
            "baseline_rate": baseline_rate,
            "treatment_rate": treatment_rate,
            "reason": "Baseline conversion is zero, so relative change is undefined.",
            "method": "two_proportion_z_test",
        }

    observed_change = (treatment_rate - baseline_rate) / baseline_rate
    pooled = (baseline_installs + treatment_installs) / (baseline_visitors + treatment_visitors)
    standard_error = math.sqrt(
        pooled * (1 - pooled) * (1 / baseline_visitors + 1 / treatment_visitors)
    )
    if standard_error == 0:
        confidence = 1.0 if baseline_rate != treatment_rate else 0.0
        z_score = 0.0
    else:
        z_score = (treatment_rate - baseline_rate) / standard_error
        two_sided_p = math.erfc(abs(z_score) / math.sqrt(2))
        confidence = max(0.0, min(1.0, 1 - two_sided_p))

    if confidence >= confidence_threshold and observed_change <= -rollback_degradation_pct:
        verdict = "rollback"
        reason = (
            f"Conversion degraded by {observed_change:.1%} at {confidence:.1%} confidence, "
            f"meeting the -{rollback_degradation_pct:.1%} rollback threshold."
        )
    elif confidence >= confidence_threshold and observed_change >= target_improvement_pct:
        verdict = "winner"
        reason = f"Conversion improved by {observed_change:.1%} at {confidence:.1%} confidence."
    elif confidence >= confidence_threshold and observed_change < 0:
        verdict = "loser"
        reason = (
            f"The measured change {observed_change:.1%} did not meet the "
            f"{target_improvement_pct:.1%} target."
        )
    elif confidence < confidence_threshold:
        verdict = "insufficient_data"
        reason = f"Result confidence is {confidence:.1%}; {confidence_threshold:.1%} is required."
    else:
        verdict = "inconclusive"
        reason = (
            f"Conversion improved by {observed_change:.1%}, below the "
            f"{target_improvement_pct:.1%} target; the treatment is not harmful."
        )
    return {
        "verdict": verdict,
        "confidence": confidence,
        "observed_change": observed_change,
        "baseline_rate": baseline_rate,
        "treatment_rate": treatment_rate,
        "z_score": z_score,
        "reason": reason,
        "method": "two_proportion_z_test",
        "baseline": {"visitors": baseline_visitors, "installs": baseline_installs},
        "treatment": {"visitors": treatment_visitors, "installs": treatment_installs},
    }


def evaluate_keyword_rank_change(
    *,
    baseline_rank: float,
    latest_rank: float,
    target_improvement_pct: float,
    rollback_degradation_pct: float,
) -> JsonDict:
    """Compare a keyword's App Store search rank before/after a listing change.

    A single rank reading has no sampling distribution -- this is deliberately
    NOT a statistical test. It's a direct, honestly-labeled threshold
    comparison, not a fabricated confidence score.
    """
    not_ranked = RANK_NOT_FOUND_SENTINEL
    was_ranked = baseline_rank < not_ranked
    is_ranked = latest_rank < not_ranked

    if not was_ranked:
        if is_ranked:
            verdict = "winner"
            reason = f"Now ranked at {latest_rank:.0f}; previously not found in search results."
            change = 1.0
        else:
            verdict = "inconclusive"
            reason = "Still not found in search results."
            change = 0.0
    elif not is_ranked:
        verdict = "rollback"
        reason = f"Lost search ranking entirely (was rank {baseline_rank:.0f})."
        change = -1.0
    else:
        change = (baseline_rank - latest_rank) / baseline_rank
        if change <= -rollback_degradation_pct:
            verdict = "rollback"
            reason = (
                f"Rank degraded from {baseline_rank:.0f} to {latest_rank:.0f} "
                f"({change:+.1%}), meeting the -{rollback_degradation_pct:.1%} rollback threshold."
            )
        elif change >= target_improvement_pct:
            verdict = "winner"
            reason = f"Rank improved from {baseline_rank:.0f} to {latest_rank:.0f} ({change:+.1%})."
        elif change < 0:
            verdict = "loser"
            reason = (
                f"Rank worsened from {baseline_rank:.0f} to {latest_rank:.0f} ({change:+.1%}), "
                f"below the {target_improvement_pct:.1%} target."
            )
        else:
            verdict = "inconclusive"
            reason = (
                f"Rank moved from {baseline_rank:.0f} to {latest_rank:.0f} ({change:+.1%}), "
                f"below the {target_improvement_pct:.1%} target; not harmful."
            )
    return {
        "verdict": verdict,
        "confidence": 1.0,
        "observed_change": change,
        "baseline_rank": baseline_rank,
        "latest_rank": latest_rank,
        "reason": reason,
        "method": "rank_threshold_comparison",
    }


class ExperimentLifecycle:
    """Own all valid experiment state transitions and external side effects."""

    def __init__(
        self,
        db_path: str | Path = DEFAULT_DB_PATH,
        *,
        rulebook_dir: str | Path | None = None,
        system_max_execution_mode: str | None = None,
        listing_reader: AsyncOrSync | None = None,
        listing_writer: AsyncOrSync | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.db_path = db_path
        self.rulebook_dir = Path(rulebook_dir or PROJECT_ROOT / "rulebooks")
        self.system_max_execution_mode = system_max_execution_mode or os.environ.get(
            "ASO_EXPERIMENT_MAX_EXECUTION_MODE", "auto_low_risk"
        )
        self.listing_reader = listing_reader or self._read_listing
        self.listing_writer = listing_writer or self._write_listing
        self.clock = clock

    def _experiment(self, experiment_id: str) -> JsonDict:
        experiment = get_db_experiment(self.db_path, experiment_id)
        if experiment is None:
            raise ExperimentNotFoundError(f"Experiment {experiment_id} not found")
        return experiment

    def _rulebook(self, package: str) -> JsonDict:
        path = self.rulebook_dir / f"{package}.yaml"
        if not path.is_file():
            return {}
        try:
            loaded = yaml.safe_load(path.read_text())
        except (OSError, yaml.YAMLError):
            return {}
        return loaded if isinstance(loaded, dict) else {}

    @staticmethod
    def _app_max_mode(rulebook: JsonDict) -> str:
        policy = rulebook.get("experiment_policy") or rulebook.get("execution_policy") or {}
        safety = rulebook.get("safety_rules") or {}
        if safety.get("require_telegram_approval") or safety.get("require_manual_approval"):
            return "manual"
        return (
            policy.get("max_execution_mode")
            or policy.get("max_mode")
            or rulebook.get("max_execution_mode")
            or "auto_low_risk"
        )

    @staticmethod
    def _semantic(experiment: JsonDict) -> JsonDict:
        result = dict(experiment)
        for field in (
            "target_args",
            "evidence_json",
            "validation_json",
            "snapshot_before",
            "snapshot_after",
            "execution_result_json",
            "evaluation_json",
        ):
            result[field] = _json_object(result.get(field)) or None
        result["evidence"] = result["evidence_json"]
        result["validation"] = result["validation_json"]
        result["rollback_snapshot"] = result["snapshot_before"]
        result["actual_listing"] = result["snapshot_after"]
        result["execution_result"] = result["execution_result_json"]
        result["evaluation"] = result["evaluation_json"]
        return result

    def create_proposal(self, proposal: Mapping[str, Any]) -> JsonDict:
        """Persist a validated proposal without coupling callers to an HTTP handler."""
        data = dict(proposal)
        experiment_id = str(uuid.uuid4())
        create_db_experiment(
            db_path=self.db_path,
            exp_id=experiment_id,
            app_package=data["app_package"],
            experiment_type=data["experiment_type"],
            hypothesis=data["hypothesis"],
            success_metric=data["success_metric"],
            baseline_value=data.get("baseline_value"),
            target_value=data.get("target_value"),
            min_observation_days=data.get("min_observation_days", 7),
            min_observation_visitors=data.get("min_observation_visitors", 1000),
            max_observation_days=data.get("max_observation_days", 28),
            rollback_threshold=data.get("rollback_degradation_pct"),
            created_by=data.get("created_by", "manual"),
            target_tool=data.get("target_tool"),
            target_args=json.dumps(data.get("target_args", {}), sort_keys=True),
            target_improvement_pct=data.get("target_improvement_pct", 0.1),
            rollback_degradation_pct=data.get("rollback_degradation_pct", 0.15),
            evidence_json=json.dumps(data.get("evidence"), sort_keys=True),
            execution_mode=data.get("execution_mode", "manual"),
        )
        self.validate(experiment_id)
        return self.detail(experiment_id)

    async def auto_advance(self, experiment_id: str) -> JsonDict:
        """Approve and execute only an unchanged, valid auto-low-risk decision."""
        detail = self.detail(experiment_id)
        validation = detail.get("validation") or {}
        if (
            detail.get("execution_mode") != "auto_low_risk"
            or validation.get("effective_execution_mode") != "auto_low_risk"
            or not validation.get("valid")
        ):
            return detail
        self.approve(
            experiment_id,
            actor="system:auto_low_risk",
            reason="Deterministic validation retained auto_low_risk authority",
        )
        return await self.execute(experiment_id)

    def detail(self, experiment_id: str) -> JsonDict:
        """Return the stable UI contract while retaining decoded raw database fields."""
        result = self._semantic(self._experiment(experiment_id))
        raw_evidence = result.get("evidence_json") or {}
        raw_validation = result.get("validation_json") or {}
        observations = get_db_observations(self.db_path, experiment_id)
        current_listing = raw_evidence.get("current_listing") or {}
        proposed_listing = raw_evidence.get("proposed_listing") or {}
        listing_fields = ("title", "short_description", "full_description")
        changes = [
            {
                "field": field,
                "before": current_listing.get(field),
                "after": proposed_listing.get(field),
            }
            for field in listing_fields
            if current_listing.get(field) != proposed_listing.get(field)
        ]
        issues = [{**issue, "severity": "error"} for issue in raw_validation.get("errors", [])] + [
            {**issue, "severity": "warning"} for issue in raw_validation.get("warnings", [])
        ]
        baseline = raw_evidence.get("baseline") or {}
        planning = raw_evidence.get("planning") or {}
        evidence_summary: list[JsonDict] = []
        if baseline:
            evidence_summary.append(
                {
                    "id": "baseline",
                    "label": "Measured baseline",
                    "value": baseline.get("value", result.get("baseline_value")),
                    "detail": (
                        f"{baseline.get('installs', 0)}/{baseline.get('visitors', 0)} installs"
                    ),
                    "source": baseline.get("source"),
                    "observed_at": baseline.get("measured_at"),
                }
            )
        listing_provenance = current_listing.get("provenance") or {}
        if current_listing:
            evidence_summary.append(
                {
                    "id": "current_listing",
                    "label": "Current listing",
                    "value": current_listing.get("language"),
                    "detail": "Live source snapshot used for the proposal diff",
                    "source": listing_provenance.get("source"),
                    "observed_at": listing_provenance.get("retrieved_at"),
                }
            )
        recommendation = planning.get("recommendation") or {}
        if planning:
            recommendation_evidence = recommendation.get("evidence") or {}
            evidence_summary.append(
                {
                    "id": "planning_design",
                    "label": "MCP experiment design" if recommendation else "Planning record",
                    "value": recommendation_evidence.get("stage") or planning.get("type_label"),
                    "detail": recommendation.get("rationale") or planning.get("notes"),
                    "source": ", ".join(recommendation_evidence.get("sources") or [])
                    or "operator_planning",
                    "observed_at": recommendation_evidence.get("captured_at")
                    or planning.get("created_at"),
                }
            )
        evaluation = result.get("evaluation_json") or {}
        result["autonomy_mode"] = result.get("execution_mode") or "manual"
        result["effective_autonomy_mode"] = raw_validation.get("effective_execution_mode")
        result["requires_review"] = (
            result["autonomy_mode"] != "recommend_only"
            and result["effective_autonomy_mode"] != "auto_low_risk"
        )
        result["proposal"] = {
            "current": {field: current_listing.get(field) for field in listing_fields},
            "proposed": {field: proposed_listing.get(field) for field in listing_fields},
            "changes": changes,
            "rulebook_version": (raw_evidence.get("rulebook") or {}).get("version")
            or (raw_evidence.get("rulebook") or {}).get("last_updated"),
            "listing_version": current_listing.get("version"),
        }
        result["raw_evidence"] = raw_evidence
        result["recommendation"] = recommendation or None
        result["evidence"] = evidence_summary
        result["validation"] = (
            {
                "valid": bool(raw_validation.get("valid")),
                "issues": issues,
                "checked_at": raw_validation.get("validated_at") or result.get("validated_at"),
                "effective_execution_mode": raw_validation.get("effective_execution_mode"),
            }
            if raw_validation
            else None
        )
        result["observations"] = observations
        result["evaluation"] = evaluation or None
        result["current_value"] = evaluation.get("treatment_rate", result.get("result_value"))
        result["days_active"] = self._days_active(result)
        result["actions"] = get_db_actions(self.db_path, experiment_id=experiment_id, limit=200)
        result["available_actions"] = self._available_actions(result, raw_validation, observations)
        result["action_links"] = [
            {
                "action": action,
                "method": "POST",
                "href": f"/api/experiments/{experiment_id}/{action}",
                "enabled": True,
            }
            for action in result["available_actions"]
        ]
        result["provenance"] = {
            "source": raw_evidence.get("rulebook_source") or baseline.get("source"),
            "captured_at": baseline.get("measured_at"),
            "locale": baseline.get("locale"),
            "is_live": True if baseline else None,
        }
        return result

    def _days_active(self, experiment: JsonDict) -> int | None:
        started = experiment.get("executed_at") or experiment.get("started_at")
        if not started:
            return None
        try:
            start = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
            if start.tzinfo is None:
                start = start.replace(tzinfo=UTC)
            end_value = experiment.get("concluded_at") or _timestamp(self.clock())
            end = datetime.fromisoformat(str(end_value).replace("Z", "+00:00"))
            if end.tzinfo is None:
                end = end.replace(tzinfo=UTC)
            return max(0, (end.date() - start.date()).days)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _available_actions(
        experiment: JsonDict,
        validation: JsonDict,
        observations: list[JsonDict],
    ) -> list[str]:
        status = experiment.get("status")
        effective_mode = validation.get("effective_execution_mode")
        valid = validation.get("valid") is True
        snapshot_available = bool(experiment.get("snapshot_before"))
        if status == "proposed":
            actions = ["reject"]
            if valid and effective_mode != "recommend_only":
                actions.insert(0, "approve")
            return actions
        if status == "approved":
            return ["execute"]
        if status == "active":
            return ["rollback"] if snapshot_available else []
        if status == "measuring":
            actions = ["evaluate"] if observations else []
            if snapshot_available:
                actions.append("rollback")
            evaluation = experiment.get("evaluation") or {}
            if evaluation.get("verdict") in {"winner", "loser", "inconclusive"}:
                actions.insert(0, "retain")
            return actions
        if status == "concluded" and snapshot_available:
            return ["rollback"]
        return []

    def validate(self, experiment_id: str) -> JsonDict:
        """Run deterministic policy validation and persist its complete result."""
        experiment = self._experiment(experiment_id)
        if experiment["status"] not in {"proposed", "approved"}:
            raise LifecycleConflictError(
                f"Cannot validate an experiment in {experiment['status']!r} state"
            )
        rulebook = self._rulebook(experiment["app_package"])
        evidence = _json_object(experiment.get("evidence_json"))
        validation: JsonDict = validate_experiment(
            experiment,
            evidence=evidence,
            rulebook=rulebook,
            active_experiments=get_db_experiments(
                self.db_path, app_package=experiment["app_package"]
            ),
            brake_active=is_emergency_brake_active(self.db_path, experiment["app_package"]),
            rollback_supported=experiment.get("target_tool") in EXECUTABLE_TOOLS,
            system_max_execution_mode=self.system_max_execution_mode,
            app_max_execution_mode=self._app_max_mode(rulebook),
            executable_locale=rulebook.get("executable_locale", EXECUTABLE_LOCALE),
            now=self.clock(),
        )
        validated_at = _timestamp(self.clock())
        validation["validated_at"] = validated_at
        fields: JsonDict = {
            "validation_json": json.dumps(validation, sort_keys=True),
            "validated_at": validated_at,
        }
        baseline = evidence.get("baseline")
        if isinstance(baseline, dict):
            visitors = baseline.get("visitors")
            installs = baseline.get("installs")
            if isinstance(visitors, int) and visitors > 0 and isinstance(installs, int):
                fields["baseline_value"] = installs / visitors
        update_db_experiment_fields(self.db_path, experiment_id, fields)
        log_db_action(
            self.db_path,
            "experiment_validate",
            app_package=experiment["app_package"],
            result="success" if validation["valid"] else "rejected",
            reasoning=json.dumps(validation, sort_keys=True),
            experiment_id=experiment_id,
        )
        return validation

    def current_policy_validation(self, experiment_id: str) -> JsonDict:
        """Re-evaluate current policy without changing lifecycle state."""
        experiment = self._experiment(experiment_id)
        rulebook = self._rulebook(experiment["app_package"])
        validation: JsonDict = validate_experiment(
            experiment,
            evidence=_json_object(experiment.get("evidence_json")),
            rulebook=rulebook,
            active_experiments=get_db_experiments(
                self.db_path, app_package=experiment["app_package"]
            ),
            brake_active=is_emergency_brake_active(self.db_path, experiment["app_package"]),
            rollback_supported=experiment.get("target_tool") in EXECUTABLE_TOOLS,
            system_max_execution_mode=self.system_max_execution_mode,
            app_max_execution_mode=self._app_max_mode(rulebook),
            executable_locale=rulebook.get("executable_locale", EXECUTABLE_LOCALE),
            now=self.clock(),
        )
        return validation

    def approve(self, experiment_id: str, *, actor: str, reason: str) -> JsonDict:
        """Approve a valid experiment with attributable operator intent."""
        if not actor.strip() or not reason.strip():
            raise LifecycleConflictError("Approval actor and reason are required")
        experiment = self._experiment(experiment_id)
        if experiment["status"] == "approved":
            return self.detail(experiment_id)
        if experiment["status"] != "proposed":
            raise LifecycleConflictError(
                f"Cannot approve an experiment in {experiment['status']!r} state"
            )
        validation = self.validate(experiment_id)
        if not validation["valid"]:
            raise LifecycleConflictError("Experiment validation failed")
        if validation["effective_execution_mode"] == "recommend_only":
            raise LifecycleConflictError("recommend_only experiments cannot be approved")

        now = _timestamp(self.clock())
        if not update_db_experiment_fields(
            self.db_path,
            experiment_id,
            {
                "status": "approved",
                "approval_actor": actor.strip(),
                "approval_reason": reason.strip(),
                "approved_at": now,
                "approved_via": validation["effective_execution_mode"],
                "approval_validation_json": json.dumps(validation, sort_keys=True),
            },
            expected_status="proposed",
        ):
            raise LifecycleConflictError("Experiment state changed during approval")
        log_db_action(
            self.db_path,
            "experiment_approve",
            app_package=experiment["app_package"],
            result="success",
            reasoning=f"Approved by {actor.strip()}: {reason.strip()}",
            experiment_id=experiment_id,
        )
        return self.detail(experiment_id)

    def reject(self, experiment_id: str, *, actor: str, reason: str) -> JsonDict:
        """Reject a proposal with attributable operator intent."""
        if not actor.strip() or not reason.strip():
            raise LifecycleConflictError("Rejection actor and reason are required")
        experiment = self._experiment(experiment_id)
        if experiment["status"] == "rejected":
            return self.detail(experiment_id)
        if experiment["status"] not in {"proposed", "approved"}:
            raise LifecycleConflictError(
                f"Cannot reject an experiment in {experiment['status']!r} state"
            )
        now = _timestamp(self.clock())
        if not update_db_experiment_fields(
            self.db_path,
            experiment_id,
            {
                "status": "rejected",
                "rejection_actor": actor.strip(),
                "rejection_reason": reason.strip(),
                "rejected_at": now,
                "concluded_at": now,
                "result_verdict": "rejected",
            },
            expected_status=experiment["status"],
        ):
            raise LifecycleConflictError("Experiment state changed during rejection")
        log_db_action(
            self.db_path,
            "experiment_reject",
            app_package=experiment["app_package"],
            result="success",
            reasoning=f"Rejected by {actor.strip()}: {reason.strip()}",
            experiment_id=experiment_id,
        )
        return self.detail(experiment_id)

    async def execute(self, experiment_id: str) -> JsonDict:
        """Execute one approved write with rollback capture and read-after-write verification."""
        try:
            assert_writes_allowed("Experiment execution")
        except WriteBlockedError as exc:
            raise LifecycleConflictError(str(exc)) from exc
        experiment = self._experiment(experiment_id)
        if (
            experiment["status"] in {"measuring", "concluded", "rolled_back"}
            and experiment.get("executed_at")
            and experiment.get("snapshot_after")
        ):
            return self.detail(experiment_id)
        if experiment["status"] == "active":
            raise LifecycleConflictError(
                "Experiment has an unresolved in-flight write and will not be retried"
            )
        if experiment["status"] != "approved":
            raise LifecycleConflictError(
                f"Cannot execute an experiment in {experiment['status']!r} state"
            )

        validation = self.validate(experiment_id)
        if not validation["valid"]:
            raise LifecycleConflictError("Experiment no longer passes execution validation")
        if validation["effective_execution_mode"] == "recommend_only":
            raise LifecycleConflictError("recommend_only experiments cannot be executed")
        if not experiment.get("approval_actor") or not experiment.get("approved_at"):
            raise LifecycleConflictError("An attributable approval is required before execution")
        if str(experiment.get("approval_actor", "")).startswith("system:") and (
            experiment.get("approved_via") != "auto_low_risk"
            or validation["effective_execution_mode"] != "auto_low_risk"
        ):
            raise LifecycleConflictError(
                "Current policy no longer grants automatic execution authority"
            )

        args = _json_object(experiment.get("target_args"))
        package = experiment["app_package"]
        language = args["language"]
        before = _as_dict(await _call(self.listing_reader, package, language))
        if not before:
            raise LifecycleConflictError("Rollback snapshot capture returned no listing")
        before = self._canonical_listing(before, package, language)
        started_at = _timestamp(self.clock())
        if not update_db_experiment_fields(
            self.db_path,
            experiment_id,
            {
                "snapshot_before": json.dumps(before, sort_keys=True),
                "status": "active",
                "started_at": started_at,
            },
            expected_status="approved",
        ):
            raise LifecycleConflictError("Experiment state changed before execution")

        log_db_action(
            self.db_path,
            "experiment_execute_started",
            app_package=package,
            tool_name=experiment["target_tool"],
            arguments=json.dumps(args, sort_keys=True),
            result="started",
            reasoning="Rollback snapshot persisted before write",
            experiment_id=experiment_id,
        )
        try:
            write_result = await _call(self.listing_writer, package, args)
        except Exception as exc:
            log_db_action(
                self.db_path,
                "experiment_execute",
                app_package=package,
                tool_name=experiment["target_tool"],
                arguments=json.dumps(args, sort_keys=True),
                result="unknown",
                reasoning=f"Write raised after dispatch; execution remains in-flight: {exc}",
                experiment_id=experiment_id,
            )
            raise
        result_dict = _as_dict(write_result)
        if not _successful(write_result):
            update_db_experiment_fields(
                self.db_path,
                experiment_id,
                {
                    "status": "approved",
                    "execution_result_json": json.dumps(result_dict, sort_keys=True),
                },
                expected_status="active",
            )
            log_db_action(
                self.db_path,
                "experiment_execute",
                app_package=package,
                tool_name=experiment["target_tool"],
                result="failed",
                reasoning=json.dumps(result_dict, sort_keys=True),
                experiment_id=experiment_id,
            )
            raise LifecycleConflictError("Listing writer reported an unsuccessful result")

        actual = self._canonical_listing(
            _as_dict(await _call(self.listing_reader, package, language)), package, language
        )
        mismatches = self._target_mismatches(args, actual)
        if mismatches:
            log_db_action(
                self.db_path,
                "experiment_execute_verify",
                app_package=package,
                tool_name=experiment["target_tool"],
                result="failed",
                reasoning=f"Read-after-write mismatch: {', '.join(mismatches)}",
                experiment_id=experiment_id,
            )
            raise PostWriteBookkeepingError(
                f"Listing write succeeded but verification failed: {', '.join(mismatches)}"
            )

        executed_at = _timestamp(self.clock())
        if not update_db_experiment_fields(
            self.db_path,
            experiment_id,
            {
                "status": "measuring",
                "snapshot_after": json.dumps(actual, sort_keys=True),
                "execution_result_json": json.dumps(result_dict, sort_keys=True),
                "executed_at": executed_at,
            },
            expected_status="active",
        ):
            raise PostWriteBookkeepingError(
                "Listing write succeeded but experiment bookkeeping failed"
            )
        log_db_action(
            self.db_path,
            "experiment_execute",
            app_package=package,
            tool_name=experiment["target_tool"],
            arguments=json.dumps(args, sort_keys=True),
            result="success",
            reasoning="Read-after-write listing matched the requested fields",
            experiment_id=experiment_id,
        )
        return self.detail(experiment_id)

    def observe(
        self,
        experiment_id: str,
        *,
        visitors: int | None = None,
        installs: int | None = None,
        rank: int | None = None,
        observed_at: str | None = None,
        period_start: str | None = None,
        period_end: str | None = None,
        source: str,
        raw_data: JsonDict | None = None,
    ) -> JsonDict:
        """Persist one non-overlapping treatment observation (conversion counts or a rank)."""
        experiment = self._experiment(experiment_id)
        if experiment["status"] != "measuring":
            raise LifecycleConflictError(
                f"Cannot observe an experiment in {experiment['status']!r} state"
            )
        is_rank_metric = experiment.get("success_metric") == KEYWORD_RANK_METRIC
        if is_rank_metric:
            if visitors is not None or installs is not None:
                raise LifecycleConflictError(
                    "keyword_rank experiments must observe rank, not visitors/installs"
                )
            if rank is not None and (
                isinstance(rank, bool) or not isinstance(rank, int) or rank <= 0
            ):
                raise LifecycleConflictError("Observation rank must be a positive integer or None")
        else:
            if rank is not None:
                raise LifecycleConflictError("Only keyword_rank experiments may observe a rank")
            if (
                isinstance(visitors, bool)
                or not isinstance(visitors, int)
                or visitors <= 0
                or isinstance(installs, bool)
                or not isinstance(installs, int)
                or installs < 0
                or installs > visitors
            ):
                raise LifecycleConflictError(
                    "Observation requires visitors > 0 and 0 <= installs <= visitors"
                )
        if not source.strip():
            raise LifecycleConflictError("Observation source is required")
        date = observed_at or self.clock().date().isoformat()
        start = period_start or date
        end = period_end or date
        try:
            calendar_date.fromisoformat(date)
            calendar_date.fromisoformat(start)
            calendar_date.fromisoformat(end)
        except ValueError as exc:
            raise LifecycleConflictError(
                "Observation dates must use ISO YYYY-MM-DD format"
            ) from exc
        if start > end:
            raise LifecycleConflictError("Observation period_start cannot follow period_end")
        if not start <= date <= end:
            raise LifecycleConflictError("observed_at must fall within the observation period")
        evidence = _json_object(experiment.get("evidence_json"))
        baseline = evidence.get("baseline") or {}
        baseline_end = baseline.get("period_end")
        if not baseline_end and baseline.get("measured_at"):
            baseline_end = str(baseline["measured_at"])[:10]
        executed_at = str(experiment.get("executed_at") or "")[:10]
        boundaries = [value for value in (baseline_end, executed_at) if value]
        if boundaries and start <= max(boundaries):
            raise LifecycleConflictError(
                "Treatment observation periods must start strictly after baseline and execution"
            )

        metric_value = (
            (float(rank) if rank is not None else RANK_NOT_FOUND_SENTINEL)
            if is_rank_metric
            else installs / visitors
        )
        insert_result = insert_db_observation_if_non_overlapping(
            self.db_path,
            experiment_id,
            date,
            metric_value,
            json.dumps(raw_data, sort_keys=True) if raw_data is not None else None,
            visitors=visitors,
            installs=installs,
            locale=_json_object(experiment.get("target_args")).get("language", EXECUTABLE_LOCALE),
            period_start=start,
            period_end=end,
            source=source.strip(),
        )
        if insert_result == "conflict":
            raise LifecycleConflictError(f"Observation {date} already exists with different counts")
        if insert_result == "overlap":
            raise LifecycleConflictError("Observation period overlaps an existing treatment period")
        if insert_result == "duplicate":
            return next(
                row
                for row in get_db_observations(self.db_path, experiment_id)
                if row["observed_at"] == date
            )
        reasoning = (
            f"Recorded rank {rank if rank is not None else 'not found'} for {date}"
            if is_rank_metric
            else f"Recorded {installs}/{visitors} conversions for {date}"
        )
        log_db_action(
            self.db_path,
            "experiment_observe",
            app_package=experiment["app_package"],
            result="success",
            reasoning=reasoning,
            experiment_id=experiment_id,
        )
        return next(
            row
            for row in get_db_observations(self.db_path, experiment_id)
            if row["observed_at"] == date
        )

    def evaluate(self, experiment_id: str) -> JsonDict:
        """Evaluate aggregate baseline/treatment counts without changing the final disposition."""
        experiment = self._experiment(experiment_id)
        if experiment["status"] != "measuring":
            if experiment.get("evaluation_json"):
                return _json_object(experiment["evaluation_json"])
            raise LifecycleConflictError(
                f"Cannot evaluate an experiment in {experiment['status']!r} state"
            )
        evidence = _json_object(experiment.get("evidence_json"))
        baseline = evidence.get("baseline") or {}
        is_rank_metric = experiment.get("success_metric") == KEYWORD_RANK_METRIC
        if is_rank_metric:
            observations = [
                item
                for item in get_db_observations(self.db_path, experiment_id)
                if item.get("phase") == "treatment"
            ]
            if not observations:
                evaluation = {
                    "verdict": "insufficient_data",
                    "confidence": 0.0,
                    "observed_change": 0.0,
                    "reason": "No rank observations recorded yet.",
                    "method": "rank_threshold_comparison",
                }
            else:
                latest = observations[-1]
                baseline_rank = float(baseline.get("rank") or RANK_NOT_FOUND_SENTINEL)
                evaluation = evaluate_keyword_rank_change(
                    baseline_rank=baseline_rank,
                    latest_rank=latest["metric_value"],
                    target_improvement_pct=experiment.get("target_improvement_pct") or 0.10,
                    rollback_degradation_pct=(
                        experiment.get("rollback_degradation_pct")
                        or experiment.get("rollback_threshold")
                        or 0.15
                    ),
                )
        else:
            observations = [
                item
                for item in get_db_observations(self.db_path, experiment_id)
                if item.get("phase") == "treatment"
                and item.get("visitors") is not None
                and item.get("installs") is not None
            ]
            treatment_visitors = sum(item["visitors"] for item in observations)
            treatment_installs = sum(item["installs"] for item in observations)
            evaluation = evaluate_two_proportion_conversion(
                baseline_visitors=baseline.get("visitors", 0),
                baseline_installs=baseline.get("installs", 0),
                treatment_visitors=treatment_visitors,
                treatment_installs=treatment_installs,
                target_improvement_pct=experiment.get("target_improvement_pct") or 0.10,
                rollback_degradation_pct=(
                    experiment.get("rollback_degradation_pct")
                    or experiment.get("rollback_threshold")
                    or 0.15
                ),
            )
        observation_days = sum(
            (
                calendar_date.fromisoformat(item.get("period_end") or item["observed_at"])
                - calendar_date.fromisoformat(item.get("period_start") or item["observed_at"])
            ).days
            + 1
            for item in observations
        )
        evaluation["observation_days"] = observation_days
        if observation_days < experiment["min_observation_days"]:
            evaluation["verdict"] = "insufficient_data"
            evaluation["reason"] = (
                f"{observation_days} observation days recorded; "
                f"{experiment['min_observation_days']} required."
            )
        elif not is_rank_metric and treatment_visitors < (
            experiment.get("min_observation_visitors") or 1000
        ):
            minimum_visitors = experiment.get("min_observation_visitors") or 1000
            evaluation["verdict"] = "insufficient_data"
            evaluation["minimum_visitors"] = minimum_visitors
            evaluation["reason"] = (
                f"{treatment_visitors} treatment visitors recorded; {minimum_visitors} required."
            )
        elif (
            evaluation["verdict"] == "insufficient_data"
            and observation_days >= experiment["max_observation_days"]
        ):
            evaluation["verdict"] = "inconclusive"
            evaluation["reason"] = "Maximum observation window reached without significance."
        evaluation["evaluated_at"] = _timestamp(self.clock())
        update_db_experiment_fields(
            self.db_path,
            experiment_id,
            {
                "evaluation_json": json.dumps(evaluation, sort_keys=True),
                "result_value": evaluation.get("treatment_rate"),
                "result_verdict": evaluation["verdict"],
                "confidence": evaluation["confidence"],
            },
            expected_status="measuring",
        )
        log_db_action(
            self.db_path,
            "experiment_evaluate",
            app_package=experiment["app_package"],
            result=evaluation["verdict"],
            reasoning=evaluation["reason"],
            experiment_id=experiment_id,
        )
        return evaluation

    def retain(self, experiment_id: str, *, actor: str, reason: str) -> JsonDict:
        """Retain the treatment listing and conclude an evaluated experiment."""
        if not actor.strip() or not reason.strip():
            raise LifecycleConflictError("Retain actor and reason are required")
        experiment = self._experiment(experiment_id)
        if experiment["status"] == "concluded" and experiment.get("retained_at"):
            return self.detail(experiment_id)
        if experiment["status"] != "measuring":
            raise LifecycleConflictError(
                f"Cannot retain an experiment in {experiment['status']!r} state"
            )
        evaluation = _json_object(experiment.get("evaluation_json"))
        if evaluation.get("verdict") not in {"winner", "loser", "inconclusive"}:
            raise LifecycleConflictError("A conclusive evaluation is required before retain")
        now = _timestamp(self.clock())
        if not update_db_experiment_fields(
            self.db_path,
            experiment_id,
            {
                "status": "concluded",
                "concluded_at": now,
                "retained_at": now,
                "result_verdict": evaluation["verdict"],
            },
            expected_status="measuring",
        ):
            raise LifecycleConflictError("Experiment state changed during retain")
        log_db_action(
            self.db_path,
            "experiment_retain",
            app_package=experiment["app_package"],
            result="success",
            reasoning=f"Retained by {actor.strip()}: {reason.strip()}",
            experiment_id=experiment_id,
        )
        return self.detail(experiment_id)

    async def rollback(self, experiment_id: str, *, actor: str, reason: str) -> JsonDict:
        """Restore and verify the persisted pre-write listing before marking rolled back."""
        if not actor.strip() or not reason.strip():
            raise LifecycleConflictError("Rollback actor and reason are required")
        experiment = self._experiment(experiment_id)
        try:
            assert_writes_allowed("Experiment rollback")
        except WriteBlockedError as exc:
            raise LifecycleConflictError(str(exc)) from exc
        if experiment["status"] == "rolled_back":
            return self.detail(experiment_id)
        if experiment["status"] not in {"active", "measuring", "concluded"}:
            raise LifecycleConflictError(
                f"Cannot roll back an experiment in {experiment['status']!r} state"
            )
        snapshot = _json_object(experiment.get("snapshot_before"))
        if not snapshot:
            raise LifecycleConflictError("No persisted rollback snapshot is available")
        package = experiment["app_package"]
        if is_emergency_brake_active(self.db_path, package):
            raise LifecycleConflictError("Emergency brake blocks rollback writes for this app")
        snapshot_after = _json_object(experiment.get("snapshot_after"))
        if not snapshot_after:
            raise LifecycleConflictError(
                "No verified post-write snapshot is available; reconciliation is required"
            )
        original_status = experiment["status"]
        if not update_db_experiment_fields(
            self.db_path,
            experiment_id,
            {"status": "rolling_back"},
            expected_status=original_status,
        ):
            raise LifecycleConflictError("Experiment state changed before rollback")
        args = {
            "packageName": package,
            "language": snapshot.get("language", EXECUTABLE_LOCALE),
            "title": snapshot.get("title"),
            "shortDescription": snapshot.get("short_description"),
            "fullDescription": snapshot.get("full_description"),
        }
        current = self._canonical_listing(
            _as_dict(await _call(self.listing_reader, package, args["language"])),
            package,
            args["language"],
        )
        drift = [
            field
            for field in ("language", "title", "short_description", "full_description", "video")
            if current.get(field) != snapshot_after.get(field)
        ]
        if drift:
            log_db_action(
                self.db_path,
                "experiment_rollback_conflict",
                app_package=package,
                result="reconciliation_required",
                reasoning=f"Remote listing drifted after treatment: {', '.join(drift)}",
                experiment_id=experiment_id,
            )
            raise LifecycleConflictError(
                "Remote listing no longer matches snapshot_after; reconciliation is required"
            )
        try:
            result = await _call(self.listing_writer, package, args)
        except Exception:
            log_db_action(
                self.db_path,
                "experiment_rollback",
                app_package=package,
                tool_name=experiment["target_tool"],
                result="unknown",
                reasoning="Rollback dispatch outcome is unknown; reconciliation is required",
                experiment_id=experiment_id,
            )
            raise
        if not _successful(result):
            result_dict = _as_dict(result)
            if result_dict.get("dispatched") is False:
                update_db_experiment_fields(
                    self.db_path,
                    experiment_id,
                    {"status": original_status},
                    expected_status="rolling_back",
                )
            log_db_action(
                self.db_path,
                "experiment_rollback",
                app_package=package,
                tool_name=experiment["target_tool"],
                result="failed",
                reasoning=json.dumps(result_dict, sort_keys=True),
                experiment_id=experiment_id,
            )
            raise LifecycleConflictError(
                "Rollback writer reported an unsuccessful result; reconcile before retrying"
            )
        actual = self._canonical_listing(
            _as_dict(await _call(self.listing_reader, package, args["language"])),
            package,
            args["language"],
        )
        mismatches = self._target_mismatches(args, actual)
        if mismatches:
            raise PostWriteBookkeepingError(
                f"Rollback write succeeded but verification failed: {', '.join(mismatches)}"
            )
        now = _timestamp(self.clock())
        if not update_db_experiment_fields(
            self.db_path,
            experiment_id,
            {
                "status": "rolled_back",
                "rolled_back_at": now,
                "concluded_at": now,
                "result_verdict": "rolled_back",
            },
            expected_status="rolling_back",
        ):
            raise PostWriteBookkeepingError("Rollback succeeded but state finalization failed")
        log_db_action(
            self.db_path,
            "experiment_rollback",
            app_package=package,
            tool_name=experiment["target_tool"],
            result="success",
            reasoning=f"Rolled back by {actor.strip()}: {reason.strip()}",
            experiment_id=experiment_id,
        )
        return self.detail(experiment_id)

    @staticmethod
    def _canonical_listing(value: JsonDict, package: str, language: str) -> JsonDict:
        return {
            "packageName": value.get("packageName", value.get("package_name", package)),
            "language": value.get("language", language),
            "title": value.get("title"),
            "short_description": value.get("short_description", value.get("shortDescription")),
            "full_description": value.get("full_description", value.get("fullDescription")),
            "video": value.get("video"),
        }

    @staticmethod
    def _target_mismatches(args: JsonDict, actual: JsonDict) -> list[str]:
        mapping = {
            "title": "title",
            "shortDescription": "short_description",
            "fullDescription": "full_description",
        }
        return [
            target
            for target, actual_field in mapping.items()
            if target in args and args[target] != actual.get(actual_field)
        ]

    @staticmethod
    def _read_listing(package: str, language: str) -> Any:
        return store_listing_client.read_listing(package, language)

    @staticmethod
    def _write_listing(package: str, args: JsonDict) -> Any:
        return store_listing_client.write_listing(package, args)
