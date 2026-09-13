"""Experiment API backed by the authoritative lifecycle service."""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal, NoReturn

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from api_server.auth import authenticated_actor, env_enabled
from app_manager.credential_store import _load_apps_config
from app_manager.experiment_lifecycle import (
    ExperimentLifecycle,
    ExperimentNotFoundError,
    LifecycleConflictError,
    LifecycleError,
)
from funnel_engine.db import (
    DEFAULT_DB_PATH,
    create_db_experiment,
    get_db_experiment,
    get_db_experiments,
    get_db_observations,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

router = APIRouter()

EXPERIMENT_TYPES: tuple[dict[str, Any], ...] = (
    {
        "id": "aso_metadata",
        "label": "Play Store metadata",
        "description": "Test title and description changes against measured store conversion.",
        "default_metric": "store_view_to_install_rate",
        "capability": "executable",
        "builder": "aso",
    },
    {
        "id": "store_creative",
        "label": "Store creative",
        "description": "Plan icon, screenshot, feature graphic, or preview-video experiments.",
        "default_metric": "store_view_to_install_rate",
        "capability": "planning_only",
    },
    {
        "id": "paywall_variant",
        "label": "Paywall variant",
        "description": "Track paywall copy, package, trial, or offering hypotheses.",
        "default_metric": "trial_to_paid_conversion_rate",
        "capability": "planning_only",
    },
    {
        "id": "pricing_experiment",
        "label": "Pricing",
        "description": "Plan price-point, localization, or purchasing-power-parity tests.",
        "default_metric": "revenue_per_payer",
        "capability": "planning_only",
    },
    {
        "id": "ad_unit_config",
        "label": "Ad configuration",
        "description": "Track ad placement, format, frequency, fill-rate, or eCPM hypotheses.",
        "default_metric": "ad_revenue_per_active_user",
        "capability": "planning_only",
    },
    {
        "id": "push_campaign",
        "label": "Push campaign",
        "description": "Plan lifecycle, churn-recovery, or re-engagement messaging tests.",
        "default_metric": "push_conversion_rate",
        "capability": "planning_only",
    },
    {
        "id": "ua_budget",
        "label": "Acquisition budget",
        "description": "Track paid campaign budget, CAC, LTV, and ROAS hypotheses.",
        "default_metric": "roas",
        "capability": "planning_only",
    },
    {
        "id": "remote_config",
        "label": "Remote configuration",
        "description": "Plan feature-flag, onboarding, monetization, or safety configuration tests.",
        "default_metric": "primary_conversion_rate",
        "capability": "planning_only",
    },
)
EXPERIMENT_TYPE_BY_ID = {item["id"]: item for item in EXPERIMENT_TYPES}


class ExperimentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app_package: str
    experiment_type: str
    hypothesis: str
    success_metric: str
    target_tool: str | None = None
    target_args: dict[str, object] = Field(default_factory=dict)
    baseline_value: float | None = None
    target_value: float | None = None
    target_improvement_pct: float = Field(default=0.1, ge=0)
    min_observation_days: int = Field(default=7, ge=1)
    min_observation_visitors: int = Field(default=1000, ge=1)
    max_observation_days: int = Field(default=28, ge=1)
    rollback_degradation_pct: float = Field(default=0.15, ge=0)
    execution_mode: Literal["recommend_only", "manual", "auto_low_risk"] = "recommend_only"
    evidence: dict[str, object] | None = None
    created_by: str = "manual"
    proposal_schema_version: str | None = None


class ExperimentStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["rejected"]
    reason: str = Field(min_length=1)


class ReasonOnly(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1)


class ObservationCreate(BaseModel):
    visitors: int = Field(gt=0)
    installs: int = Field(ge=0)
    observed_at: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    source: str = Field(min_length=1)
    raw_data: dict[str, object] | None = None


class PlannedExperimentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app_package: str = Field(min_length=1)
    experiment_type: str = Field(min_length=1)
    hypothesis: str = Field(min_length=8)
    success_metric: str | None = None
    min_observation_days: int = Field(default=7, ge=1, le=90)
    max_observation_days: int = Field(default=28, ge=1, le=180)
    notes: str | None = Field(default=None, max_length=4000)
    recommendation: dict[str, object] | None = None


def _service() -> ExperimentLifecycle:
    return ExperimentLifecycle(DEFAULT_DB_PATH)


def _raise_lifecycle(error: LifecycleError) -> NoReturn:
    if isinstance(error, ExperimentNotFoundError):
        raise HTTPException(status_code=404, detail=str(error))
    if isinstance(error, LifecycleConflictError):
        raise HTTPException(status_code=409, detail=str(error))
    raise HTTPException(status_code=500, detail=str(error))


def create_experiment_proposal(proposal: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and persist a full proposal through the lifecycle service."""
    data = ExperimentCreate.model_validate(dict(proposal))
    return _service().create_proposal(data.model_dump())


async def auto_advance_experiment_proposal(experiment_id: str) -> dict[str, Any]:
    """Apply automatic approval/execution only when policy retains auto authority."""
    return await _service().auto_advance(experiment_id)


@router.get("/")
def list_experiments(
    app: str | None = None, status: str | None = None
) -> dict[str, list[dict[str, Any]]]:
    """List experiment summaries from SQLite."""
    try:
        return {"experiments": get_db_experiments(DEFAULT_DB_PATH, app_package=app, status=status)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/types")
def list_experiment_types() -> dict[str, list[dict[str, Any]]]:
    """Return the complete experiment catalog and current execution capability."""
    return {"experiment_types": [dict(item) for item in EXPERIMENT_TYPES]}


@router.post("/planned")
def create_planned_experiment(data: PlannedExperimentCreate, request: Request) -> dict[str, Any]:
    """Create a recommendation-only experiment for a not-yet-executable integration."""
    experiment_type = EXPERIMENT_TYPE_BY_ID.get(data.experiment_type)
    if experiment_type is None:
        raise HTTPException(status_code=422, detail="Unsupported experiment type")
    if experiment_type["capability"] == "executable":
        raise HTTPException(
            status_code=409,
            detail="Play Store metadata experiments must use the evidence-backed ASO builder",
        )
    if data.max_observation_days < data.min_observation_days:
        raise HTTPException(
            status_code=422,
            detail="max_observation_days must be greater than or equal to min_observation_days",
        )
    if data.recommendation and data.recommendation.get("experiment_type") != data.experiment_type:
        raise HTTPException(status_code=422, detail="Recommendation experiment type does not match")
    configured_packages = {
        str(app.get("package_name")) for app in _load_apps_config() if app.get("package_name")
    }
    if data.app_package not in configured_packages:
        raise HTTPException(status_code=404, detail="App is not configured in this portfolio")

    experiment_id = str(uuid.uuid4())
    metric = (data.success_metric or str(experiment_type["default_metric"])).strip()
    evidence = {
        "planning": {
            "type_label": experiment_type["label"],
            "capability": "planning_only",
            "execution_supported": False,
            "created_at": datetime.now(UTC).isoformat(),
            "notes": data.notes.strip() if data.notes else None,
            "recommendation": data.recommendation,
        }
    }
    try:
        create_db_experiment(
            db_path=DEFAULT_DB_PATH,
            exp_id=experiment_id,
            app_package=data.app_package,
            experiment_type=data.experiment_type,
            hypothesis=data.hypothesis.strip(),
            success_metric=metric,
            min_observation_days=data.min_observation_days,
            max_observation_days=data.max_observation_days,
            created_by=authenticated_actor(request),
            target_args="{}",
            evidence_json=json.dumps(evidence, sort_keys=True),
            execution_mode="recommend_only",
        )
        return {
            "experiment": _service().detail(experiment_id),
            "message": "Planning experiment created. Execution remains disabled for this type.",
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/")
def create_experiment(data: ExperimentCreate) -> dict[str, str]:
    """Create a non-executable note unless explicit local compatibility is enabled."""
    if data.max_observation_days < data.min_observation_days:
        raise HTTPException(
            status_code=422,
            detail="max_observation_days must be greater than or equal to min_observation_days",
        )
    executable = data.target_tool is not None or data.execution_mode != "recommend_only"
    if executable and not env_enabled("MCP_GC_DEV_ALLOW_GENERIC_EXECUTABLE_PROPOSALS"):
        raise HTTPException(
            status_code=403,
            detail=(
                "Executable proposals must use the server-owned store-conversion proposal endpoint"
            ),
        )
    if executable and os.environ.get("MCP_GC_ENV", "local").strip().lower() not in {
        "local",
        "dev",
        "development",
        "test",
    }:
        raise HTTPException(
            status_code=403, detail="Generic executable proposal compatibility is local-only"
        )
    exp_id = str(uuid.uuid4())
    try:
        create_db_experiment(
            db_path=DEFAULT_DB_PATH,
            exp_id=exp_id,
            app_package=data.app_package,
            experiment_type=data.experiment_type,
            hypothesis=data.hypothesis,
            success_metric=data.success_metric,
            baseline_value=data.baseline_value,
            target_value=data.target_value,
            min_observation_days=data.min_observation_days,
            min_observation_visitors=data.min_observation_visitors,
            max_observation_days=data.max_observation_days,
            rollback_threshold=data.rollback_degradation_pct,
            created_by=data.created_by,
            target_tool=data.target_tool,
            target_args=json.dumps(data.target_args, sort_keys=True),
            target_improvement_pct=data.target_improvement_pct,
            rollback_degradation_pct=data.rollback_degradation_pct,
            evidence_json=json.dumps(data.evidence, sort_keys=True) if data.evidence else None,
            execution_mode=data.execution_mode,
        )
        return {"message": "Experiment created successfully", "id": exp_id}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{id}")
def get_experiment(id: str) -> dict[str, Any]:
    """Return semantic experiment detail with evidence, observations, and actions."""
    try:
        return _service().detail(id)
    except LifecycleError as exc:
        _raise_lifecycle(exc)


@router.patch("/{id}")
def update_experiment(id: str, data: ExperimentStatusUpdate, request: Request) -> dict[str, Any]:
    """Deprecated generic mutation surface, retained only for attributable rejection."""
    try:
        experiment = _service().reject(id, actor=authenticated_actor(request), reason=data.reason)
        return {"experiment": experiment, "message": "Experiment rejected"}
    except LifecycleError as exc:
        _raise_lifecycle(exc)


@router.post("/{id}/validate")
def validate_experiment(id: str) -> dict[str, Any]:
    try:
        service = _service()
        validation = service.validate(id)
        return {
            "experiment": service.detail(id),
            "validation": validation,
            "message": "Experiment validation completed",
        }
    except LifecycleError as exc:
        _raise_lifecycle(exc)


@router.post("/{id}/approve")
def approve_experiment(id: str, data: ReasonOnly, request: Request) -> dict[str, Any]:
    try:
        experiment = _service().approve(id, actor=authenticated_actor(request), reason=data.reason)
        return {"experiment": experiment, "message": "Experiment approved"}
    except LifecycleError as exc:
        _raise_lifecycle(exc)


@router.post("/{id}/reject")
def reject_experiment(id: str, data: ReasonOnly, request: Request) -> dict[str, Any]:
    try:
        experiment = _service().reject(id, actor=authenticated_actor(request), reason=data.reason)
        return {"experiment": experiment, "message": "Experiment rejected"}
    except LifecycleError as exc:
        _raise_lifecycle(exc)


@router.post("/{id}/execute")
async def execute_experiment(id: str) -> dict[str, Any]:
    try:
        experiment = await _service().execute(id)
        return {"experiment": experiment, "message": "Experiment executed"}
    except LifecycleError as exc:
        _raise_lifecycle(exc)


@router.post("/{id}/observe")
def observe_experiment(id: str, data: ObservationCreate) -> dict[str, Any]:
    if data.installs > data.visitors:
        raise HTTPException(status_code=422, detail="installs cannot exceed visitors")
    try:
        service = _service()
        observation = service.observe(
            id,
            visitors=data.visitors,
            installs=data.installs,
            observed_at=data.observed_at,
            period_start=data.period_start,
            period_end=data.period_end,
            source=data.source,
            raw_data=data.raw_data,
        )
        return {
            "experiment": service.detail(id),
            "observation": observation,
            "message": "Treatment observation recorded",
        }
    except LifecycleError as exc:
        _raise_lifecycle(exc)


@router.post("/{id}/evaluate")
def evaluate_experiment(id: str) -> dict[str, Any]:
    try:
        service = _service()
        evaluation = service.evaluate(id)
        return {
            "experiment": service.detail(id),
            "evaluation": evaluation,
            "message": "Experiment evaluated",
        }
    except LifecycleError as exc:
        _raise_lifecycle(exc)


@router.post("/{id}/retain")
def retain_experiment(id: str, data: ReasonOnly, request: Request) -> dict[str, Any]:
    try:
        experiment = _service().retain(id, actor=authenticated_actor(request), reason=data.reason)
        return {"experiment": experiment, "message": "Treatment retained"}
    except LifecycleError as exc:
        _raise_lifecycle(exc)


@router.post("/{id}/rollback")
async def rollback_experiment(id: str, data: ReasonOnly, request: Request) -> dict[str, Any]:
    try:
        experiment = await _service().rollback(
            id, actor=authenticated_actor(request), reason=data.reason
        )
        return {"experiment": experiment, "message": "Experiment rolled back"}
    except LifecycleError as exc:
        _raise_lifecycle(exc)


@router.get("/{id}/observations")
def get_experiment_observations(id: str) -> dict[str, list[dict[str, Any]]]:
    """Get count-bearing metric observations for an experiment."""
    if get_db_experiment(DEFAULT_DB_PATH, id) is None:
        raise HTTPException(status_code=404, detail=f"Experiment {id} not found")
    return {"observations": get_db_observations(DEFAULT_DB_PATH, experiment_id=id)}
