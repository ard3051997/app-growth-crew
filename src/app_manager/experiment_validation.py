"""Pure, deterministic validation for executable ASO experiments."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

EXECUTION_MODES = ("recommend_only", "manual", "auto_low_risk")
EXECUTION_MODE_RANK = {mode: rank for rank, mode in enumerate(EXECUTION_MODES)}
EXECUTABLE_EXPERIMENT_TYPE = "aso_metadata"
EXECUTABLE_TOOL = "play_store/update_listing"
EXECUTABLE_TOOLS = frozenset({"play_store/update_listing", "app_store_connect/update_listing"})
EXECUTABLE_METRIC = "store_view_to_install_rate"
KEYWORD_RANK_METRIC = "keyword_rank"
EXECUTABLE_METRICS = frozenset({EXECUTABLE_METRIC, KEYWORD_RANK_METRIC})
EXECUTABLE_LOCALE = "en-US"
BASELINE_MAX_AGE_DAYS = 7
STORE_TEXT_LIMITS = {
    "title": 30,
    "short_description": 80,
    "full_description": 4000,
}


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def resolve_execution_mode(
    requested: str | None,
    system_max: str = "auto_low_risk",
    app_max: str = "auto_low_risk",
) -> tuple[str, list[dict[str, str]]]:
    """Resolve an experiment mode against system and app maximum policies."""
    errors: list[dict[str, str]] = []
    selected = requested or "manual"
    for field, mode in (
        ("execution_mode", selected),
        ("system_max_execution_mode", system_max),
        ("app_max_execution_mode", app_max),
    ):
        if mode not in EXECUTION_MODE_RANK:
            errors.append(
                {
                    "code": "invalid_execution_mode",
                    "field": field,
                    "message": f"{mode!r} is not a supported execution mode",
                }
            )
    if errors:
        return selected, errors

    effective = min((selected, system_max, app_max), key=EXECUTION_MODE_RANK.__getitem__)
    if effective != selected:
        errors.append(
            {
                "code": "execution_mode_exceeds_policy",
                "field": "execution_mode",
                "message": (
                    f"Requested mode {selected!r} exceeds the effective maximum {effective!r}"
                ),
            }
        )
    return effective, errors


def validate_experiment(
    experiment: dict[str, Any],
    *,
    evidence: dict[str, Any] | None = None,
    rulebook: dict[str, Any] | None = None,
    active_experiments: list[dict[str, Any]] | None = None,
    brake_active: bool = False,
    rollback_supported: bool = True,
    system_max_execution_mode: str = "auto_low_risk",
    app_max_execution_mode: str = "auto_low_risk",
    executable_locale: str = EXECUTABLE_LOCALE,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate the only currently executable experiment shape without performing I/O."""
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    def error(code: str, field: str, message: str) -> None:
        errors.append({"code": code, "field": field, "message": message})

    mode, mode_errors = resolve_execution_mode(
        experiment.get("execution_mode"),
        system_max_execution_mode,
        app_max_execution_mode,
    )
    for issue in mode_errors:
        if issue["code"] == "execution_mode_exceeds_policy":
            warnings.append(issue)
        else:
            errors.append(issue)

    if experiment.get("experiment_type") != EXECUTABLE_EXPERIMENT_TYPE:
        error(
            "unsupported_golden_path",
            "experiment_type",
            f"Executable experiments require {EXECUTABLE_EXPERIMENT_TYPE!r}",
        )
    if experiment.get("success_metric") not in EXECUTABLE_METRICS:
        error(
            "unsupported_golden_path",
            "success_metric",
            f"Executable experiments require success_metric in {sorted(EXECUTABLE_METRICS)!r}",
        )
    if experiment.get("target_tool") not in EXECUTABLE_TOOLS:
        error(
            "unsupported_golden_path",
            "target_tool",
            f"Executable experiments require target_tool in {sorted(EXECUTABLE_TOOLS)!r}",
        )

    args = _json_object(experiment.get("target_args"))
    allowed_args = {
        "packageName",
        "language",
        "title",
        "shortDescription",
        "fullDescription",
    }
    unknown_args = sorted(set(args) - allowed_args)
    if unknown_args:
        error(
            "unsupported_target_argument",
            "target_args",
            f"Unsupported listing arguments: {', '.join(unknown_args)}",
        )
    if args.get("packageName") != experiment.get("app_package"):
        error(
            "package_mismatch",
            "target_args.packageName",
            "Target package must exactly match the experiment app",
        )
    if args.get("language") != executable_locale:
        error(
            "unsupported_locale",
            "target_args.language",
            f"Executable experiments require locale {executable_locale}",
        )

    target_text = {
        "title": args.get("title"),
        "short_description": args.get("shortDescription"),
        "full_description": args.get("fullDescription"),
    }
    if not any(isinstance(value, str) and value.strip() for value in target_text.values()):
        error(
            "empty_listing_change",
            "target_args",
            "At least one non-empty listing text field must be changed",
        )

    constraints = (rulebook or {}).get("metadata_constraints") or {}
    rulebook_package = (rulebook or {}).get("package_name")
    if rulebook_package and rulebook_package != experiment.get("app_package"):
        error(
            "rulebook_package_mismatch",
            "rulebook.package_name",
            "Rulebook package does not match the experiment app",
        )
    for field, value in target_text.items():
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip():
            error("invalid_listing_text", f"target_args.{field}", "Listing text must be non-empty")
            continue
        configured_limit = (constraints.get(field) or {}).get("max_length")
        limit = STORE_TEXT_LIMITS[field]
        if isinstance(configured_limit, int) and configured_limit > 0:
            limit = min(limit, configured_limit)
        if len(value) > limit:
            error(
                "listing_text_too_long",
                f"target_args.{field}",
                f"{field} exceeds the deterministic {limit}-character limit",
            )

        field_rules = constraints.get(field) or {}
        lowered = value.casefold()
        missing = [
            keyword
            for keyword in field_rules.get("required_keywords", [])
            if str(keyword).casefold() not in lowered
        ]
        if missing:
            error(
                "required_keyword_missing",
                f"target_args.{field}",
                f"Missing required keywords: {', '.join(str(item) for item in missing)}",
            )
        prohibited = [
            keyword
            for keyword in field_rules.get("prohibited_keywords", [])
            if str(keyword).casefold() in lowered
        ]
        if prohibited:
            error(
                "prohibited_keyword",
                f"target_args.{field}",
                f"Contains prohibited keywords: {', '.join(str(item) for item in prohibited)}",
            )

    baseline = (evidence or _json_object(experiment.get("evidence_json"))).get("baseline")
    if not isinstance(baseline, dict):
        error(
            "missing_baseline_evidence",
            "evidence.baseline",
            "Measured baseline evidence is required",
        )
        baseline = {}
    baseline_metric = baseline.get("metric")
    if baseline_metric not in EXECUTABLE_METRICS:
        error(
            "baseline_metric_mismatch",
            "evidence.baseline.metric",
            f"Baseline metric must be one of {sorted(EXECUTABLE_METRICS)!r}",
        )
    elif baseline_metric == KEYWORD_RANK_METRIC:
        # A brand-new app with too little install volume for a conversion-rate
        # baseline to be meaningful can use a real App Store search rank instead.
        # rank is nullable: None means "not currently ranked" -- itself a valid,
        # measurable starting point, not missing data.
        keyword = baseline.get("keyword")
        rank = baseline.get("rank")
        if not isinstance(keyword, str) or not keyword.strip():
            error(
                "invalid_baseline_counts",
                "evidence.baseline.keyword",
                "Keyword-rank baseline requires a non-empty keyword",
            )
        if rank is not None and (isinstance(rank, bool) or not isinstance(rank, int) or rank <= 0):
            error(
                "invalid_baseline_counts",
                "evidence.baseline.rank",
                "Keyword-rank baseline requires rank to be null (not ranked) or a positive integer",
            )
    else:
        visitors = baseline.get("visitors")
        installs = baseline.get("installs")
        if (
            isinstance(visitors, bool)
            or not isinstance(visitors, int)
            or visitors <= 0
            or isinstance(installs, bool)
            or not isinstance(installs, int)
            or installs < 0
            or installs > visitors
        ):
            error(
                "invalid_baseline_counts",
                "evidence.baseline",
                "Baseline requires integer visitors > 0 and 0 <= installs <= visitors",
            )
    if baseline.get("locale") != executable_locale:
        error(
            "baseline_locale_mismatch",
            "evidence.baseline.locale",
            f"Baseline locale must be {executable_locale}",
        )
    measured_at = _parse_datetime(baseline.get("measured_at"))
    reference_time = (now or datetime.now(UTC)).astimezone(UTC)
    if measured_at is None:
        error(
            "invalid_baseline_timestamp",
            "evidence.baseline.measured_at",
            "Baseline measured_at must be an ISO-8601 timestamp",
        )
    elif (
        measured_at > reference_time or (reference_time - measured_at).days > BASELINE_MAX_AGE_DAYS
    ):
        error(
            "stale_baseline",
            "evidence.baseline.measured_at",
            f"Baseline must be measured within {BASELINE_MAX_AGE_DAYS} days",
        )
    if not baseline.get("source"):
        error("missing_baseline_source", "evidence.baseline.source", "Baseline source is required")

    if brake_active:
        error("emergency_brake_active", "app_package", "An emergency brake blocks execution")
    if not rollback_supported:
        error("rollback_unsupported", "target_tool", "A tested rollback path is required")

    for active in active_experiments or []:
        if active.get("id") == experiment.get("id"):
            continue
        if active.get("app_package") != experiment.get("app_package"):
            continue
        if active.get("status") not in {"active", "measuring"}:
            continue
        error(
            "conflicting_experiment",
            "app_package",
            f"Experiment {active.get('id')} already controls this app listing",
        )
        break

    if mode == "recommend_only":
        warnings.append(
            {
                "code": "recommend_only",
                "field": "execution_mode",
                "message": "This experiment may be reviewed but cannot be approved or executed",
            }
        )

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "effective_execution_mode": mode,
        "rulebook_package": rulebook_package,
        "validator_version": 1,
    }
