"""Pure construction and validation of measured store-conversion proposals."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal, Protocol

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

if TYPE_CHECKING:
    from pathlib import Path


PROPOSAL_SCHEMA_VERSION = "store-conversion-proposal.v1"
PLAY_TITLE_MAX_LENGTH = 30
PLAY_SHORT_DESCRIPTION_MAX_LENGTH = 80
PLAY_FULL_DESCRIPTION_MAX_LENGTH = 4_000
PACKAGE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+$")
UNMEASURED_SOURCES = frozenset({"fallback", "mock", "mocked", "synthetic", "sample"})


class ProposalDataError(ValueError):
    """Raised when source data cannot support a safe, measured proposal."""

    def __init__(self, message: str, *, code: str, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


class ListingText(BaseModel):
    """Store listing text accepted from an operator or an ASO generator."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=PLAY_TITLE_MAX_LENGTH)
    short_description: str | None = Field(
        default=None, min_length=1, max_length=PLAY_SHORT_DESCRIPTION_MAX_LENGTH
    )
    full_description: str | None = Field(
        default=None, min_length=1, max_length=PLAY_FULL_DESCRIPTION_MAX_LENGTH
    )

    @model_validator(mode="after")
    def require_a_change(self) -> ListingText:
        if not any(
            value is not None
            for value in (self.title, self.short_description, self.full_description)
        ):
            raise ValueError("At least one proposed listing field is required")
        return self


class StoreConversionProposalRequest(BaseModel):
    """Operator controls for generating one store conversion proposal."""

    model_config = ConfigDict(extra="forbid")

    # Not restricted to en-US: which single locale is actually executable for a given
    # app is enforced per-app by validate_experiment's executable_locale check (driven
    # by that app's rulebook), not by this request shape.
    language: str = Field(default="en-US", pattern=r"^[a-zA-Z]{2}-[a-zA-Z]{2}$")
    country: str = Field(default="us", pattern=r"^[a-zA-Z]{2}$")
    baseline_window_days: int = Field(default=7, ge=3, le=28)
    max_source_age_days: int = Field(default=3, ge=0, le=7)
    target_improvement_pct: float = Field(default=0.1, gt=0, le=1)
    rollback_degradation_pct: float = Field(default=0.15, gt=0, le=1)
    min_observation_days: int = Field(default=7, ge=1, le=90)
    min_observation_visitors: int = Field(default=1000, ge=1)
    max_observation_days: int = Field(default=28, ge=1, le=180)
    proposed_listing: ListingText | None = None
    execution_mode: Literal["recommend_only", "manual", "auto_low_risk"] = "manual"

    @model_validator(mode="after")
    def validate_observation_window(self) -> StoreConversionProposalRequest:
        if self.max_observation_days < self.min_observation_days:
            raise ValueError("max_observation_days must be at least min_observation_days")
        return self


class ListingProvenance(BaseModel):
    source: str
    live: bool
    retrieved_at: datetime


class ListingSnapshot(BaseModel):
    title: str
    short_description: str
    full_description: str
    language: str
    provenance: ListingProvenance


class DailyConversion(BaseModel):
    date: date
    visitors: int
    installs: int
    conversion_rate: float
    country_rows: int


class BaselineEvidence(BaseModel):
    metric: str = "store_view_to_install_rate"
    value: float
    visitors: int
    installs: int
    period_start: date
    period_end: date
    window_days: int
    observed_days: int
    completeness_ratio: float
    source_age_days: int
    source: str
    locale: str
    measured_at: datetime
    granularity: str = "daily_country"
    measured: bool = True
    synthetic: bool = False
    daily: list[DailyConversion]


class ExperimentProposal(BaseModel):
    app_package: str
    experiment_type: str = "aso_metadata"
    hypothesis: str
    success_metric: str = "store_view_to_install_rate"
    target_tool: str = "play_store/update_listing"
    target_args: dict[str, object]
    baseline_value: float
    target_value: float
    target_improvement_pct: float
    min_observation_days: int
    min_observation_visitors: int
    max_observation_days: int
    rollback_degradation_pct: float
    created_by: str


class ProposalEvidence(BaseModel):
    baseline: BaselineEvidence
    current_listing: ListingSnapshot
    proposed_listing: ListingSnapshot
    rulebook: dict[str, Any]
    rulebook_source: str


class CanonicalStoreConversionProposal(BaseModel):
    schema_version: str = PROPOSAL_SCHEMA_VERSION
    execution_mode: Literal["recommend_only", "manual", "auto_low_risk"] = "manual"
    experiment: ExperimentProposal
    evidence: ProposalEvidence

    def lifecycle_payload(self) -> dict[str, Any]:
        """Return the flat contract consumed by the experiment lifecycle creator."""
        payload: dict[str, Any] = self.experiment.model_dump(mode="json")
        payload["evidence"] = self.evidence.model_dump(mode="json")
        payload["proposal_schema_version"] = self.schema_version
        payload["execution_mode"] = self.execution_mode
        return payload


class LifecycleProposalCreator(Protocol):
    """Lifecycle-owned persistence boundary used by the API integration."""

    def __call__(self, proposal: Mapping[str, Any], /) -> Mapping[str, Any]: ...


def _parse_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise TypeError("date must be an ISO date string")
    normalized = value.strip()
    try:
        if re.fullmatch(r"\d{8}", normalized):
            return datetime.strptime(normalized, "%Y%m%d").date()
        return date.fromisoformat(normalized[:10])
    except ValueError as exc:
        raise ValueError(f"invalid storefront date: {value!r}") from exc


def _nonnegative_count(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be a non-negative integer")
    if value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _row_is_synthetic(row: Mapping[str, Any]) -> bool:
    if row.get("synthetic") is True or row.get("is_synthetic") is True:
        return True
    source = str(row.get("source", "")).strip().lower()
    return any(marker in source for marker in UNMEASURED_SOURCES)


def derive_measured_baseline(
    rows: Sequence[Mapping[str, Any]],
    *,
    window_days: int = 7,
    max_source_age_days: int = 3,
    as_of: date | None = None,
    source: str = "play_console_gcs_store_performance",
    locale: str = "en-US",
) -> BaselineEvidence:
    """Aggregate normalized country rows into a complete, visitor-weighted daily baseline."""
    if not rows:
        raise ProposalDataError(
            "No storefront country observations are available",
            code="baseline_missing",
        )
    if any(_row_is_synthetic(row) for row in rows):
        raise ProposalDataError(
            "Synthetic or fallback storefront observations cannot form a baseline",
            code="baseline_synthetic",
        )
    if any(marker in source.lower() for marker in UNMEASURED_SOURCES):
        raise ProposalDataError(
            "The storefront source is not a measured source",
            code="baseline_synthetic",
        )

    today = as_of or datetime.now(UTC).date()
    aggregates: dict[date, dict[str, int]] = defaultdict(
        lambda: {"visitors": 0, "installs": 0, "country_rows": 0}
    )
    try:
        for row in rows:
            observed_on = _parse_date(row.get("date"))
            visitors = _nonnegative_count(row.get("visitors"), "visitors")
            installs = _nonnegative_count(row.get("installs"), "installs")
            if installs > visitors:
                raise ValueError("installs cannot exceed visitors")
            aggregates[observed_on]["visitors"] += visitors
            aggregates[observed_on]["installs"] += installs
            aggregates[observed_on]["country_rows"] += 1
    except (TypeError, ValueError) as exc:
        raise ProposalDataError(
            f"Invalid normalized storefront country row: {exc}",
            code="baseline_invalid",
        ) from exc

    latest = max(aggregates)
    if latest > today:
        raise ProposalDataError(
            "The storefront source contains future-dated observations",
            code="baseline_future_dated",
            details={"latest_observation_date": latest.isoformat(), "as_of": today.isoformat()},
        )
    source_age = (today - latest).days
    if source_age > max_source_age_days:
        raise ProposalDataError(
            f"Storefront observations are stale ({source_age} days old)",
            code="baseline_stale",
            details={
                "latest_observation_date": latest.isoformat(),
                "source_age_days": source_age,
                "max_source_age_days": max_source_age_days,
            },
        )

    period_start = latest - timedelta(days=window_days - 1)
    expected_dates = [period_start + timedelta(days=offset) for offset in range(window_days)]
    missing_dates = [observed_on for observed_on in expected_dates if observed_on not in aggregates]
    if missing_dates:
        raise ProposalDataError(
            "Storefront baseline does not contain every day in the requested window",
            code="baseline_incomplete",
            details={
                "period_start": period_start.isoformat(),
                "period_end": latest.isoformat(),
                "observed_days": window_days - len(missing_dates),
                "required_days": window_days,
                "missing_dates": [value.isoformat() for value in missing_dates],
            },
        )

    daily: list[DailyConversion] = []
    total_visitors = 0
    total_installs = 0
    for observed_on in expected_dates:
        aggregate = aggregates[observed_on]
        visitors = aggregate["visitors"]
        installs = aggregate["installs"]
        if visitors <= 0:
            raise ProposalDataError(
                f"Storefront baseline has no visitors on {observed_on.isoformat()}",
                code="baseline_incomplete",
                details={"date": observed_on.isoformat()},
            )
        total_visitors += visitors
        total_installs += installs
        daily.append(
            DailyConversion(
                date=observed_on,
                visitors=visitors,
                installs=installs,
                conversion_rate=installs / visitors,
                country_rows=aggregate["country_rows"],
            )
        )

    if total_visitors <= 0:
        raise ProposalDataError(
            "Storefront baseline has no measured visitors",
            code="baseline_missing",
        )
    return BaselineEvidence(
        value=total_installs / total_visitors,
        visitors=total_visitors,
        installs=total_installs,
        period_start=period_start,
        period_end=latest,
        window_days=window_days,
        observed_days=len(daily),
        completeness_ratio=len(daily) / window_days,
        source_age_days=source_age,
        source=source,
        locale=locale,
        measured_at=datetime(latest.year, latest.month, latest.day, tzinfo=UTC),
        daily=daily,
    )


def validate_package_name(package: str) -> str:
    """Reject path-like and malformed package values before filesystem access."""
    if not PACKAGE_PATTERN.fullmatch(package):
        raise ProposalDataError("Invalid app package name", code="invalid_package")
    return package


def load_rulebook(package: str, *, project_root: Path) -> tuple[dict[str, Any], Path]:
    """Safely load a package-bound YAML rulebook from the configured root."""
    validate_package_name(package)
    path = project_root / "rulebooks" / f"{package}.yaml"
    if not path.is_file():
        raise ProposalDataError(
            f"No rulebook is configured for {package}",
            code="rulebook_missing",
        )
    if path.stat().st_size > 256 * 1024:
        raise ProposalDataError("Rulebook exceeds the size limit", code="rulebook_invalid")
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ProposalDataError("Rulebook could not be read", code="rulebook_invalid") from exc
    if not isinstance(loaded, dict) or not all(isinstance(key, str) for key in loaded):
        raise ProposalDataError("Rulebook must be a YAML object", code="rulebook_invalid")
    declared_package = loaded.get("package_name")
    if declared_package not in (None, package):
        raise ProposalDataError(
            "Rulebook package does not match the requested app",
            code="rulebook_invalid",
        )
    return loaded, path


def redact_rulebook(value: Any) -> Any:
    """Remove credential-like values before returning a rulebook over HTTP."""
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).lower()
            if any(
                marker in normalized
                for marker in (
                    "secret",
                    "password",
                    "token",
                    "credential",
                    "private_key",
                    "api_key",
                )
            ):
                redacted[str(key)] = "********" if item else item
            else:
                redacted[str(key)] = redact_rulebook(item)
        return redacted
    if isinstance(value, list):
        return [redact_rulebook(item) for item in value]
    return value


def _constraint(rulebook: Mapping[str, Any], field: str) -> Mapping[str, Any]:
    constraints = rulebook.get("metadata_constraints", {})
    if not isinstance(constraints, Mapping):
        raise ProposalDataError(
            "Rulebook metadata_constraints must be an object", code="rulebook_invalid"
        )
    value = constraints.get(field, {})
    if not isinstance(value, Mapping):
        raise ProposalDataError(
            f"Rulebook constraint {field} must be an object", code="rulebook_invalid"
        )
    return value


def _safe_max_length(constraint: Mapping[str, Any], hard_limit: int, field: str) -> int:
    configured = constraint.get("max_length", hard_limit)
    if isinstance(configured, bool) or not isinstance(configured, int) or configured <= 0:
        raise ProposalDataError(
            f"Rulebook max_length for {field} must be a positive integer",
            code="rulebook_invalid",
        )
    return min(int(configured), hard_limit)


def _complete_listing(candidate: ListingText, current: ListingSnapshot) -> dict[str, str]:
    return {
        "title": candidate.title or current.title,
        "short_description": candidate.short_description or current.short_description,
        "full_description": candidate.full_description or current.full_description,
    }


def validate_listing_candidate(
    candidate: ListingText,
    *,
    current: ListingSnapshot,
    rulebook: Mapping[str, Any],
) -> dict[str, str]:
    """Complete a partial candidate from live state and enforce Play and rulebook limits."""
    completed = _complete_listing(candidate, current)
    fields = (
        ("title", PLAY_TITLE_MAX_LENGTH),
        ("short_description", PLAY_SHORT_DESCRIPTION_MAX_LENGTH),
        ("full_description", PLAY_FULL_DESCRIPTION_MAX_LENGTH),
    )
    for field, hard_limit in fields:
        value = completed[field]
        if not value.strip():
            raise ProposalDataError(f"Proposed {field} cannot be empty", code="listing_invalid")
        if any(ord(character) < 32 and character not in "\n\t" for character in value):
            raise ProposalDataError(
                f"Proposed {field} contains control characters",
                code="listing_invalid",
            )
        constraint = _constraint(rulebook, field)
        max_length = _safe_max_length(constraint, hard_limit, field)
        if len(value) > max_length:
            raise ProposalDataError(
                f"Proposed {field} exceeds the {max_length}-character limit",
                code="listing_invalid",
                details={"field": field, "length": len(value), "max_length": max_length},
            )

    title_constraint = _constraint(rulebook, "title")
    required = title_constraint.get("required_keywords", [])
    if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
        raise ProposalDataError(
            "title.required_keywords must be a string list", code="rulebook_invalid"
        )
    missing = [
        keyword for keyword in required if keyword.casefold() not in completed["title"].casefold()
    ]
    if missing:
        raise ProposalDataError(
            "Proposed title is missing required rulebook keywords",
            code="listing_invalid",
            details={"missing_required_keywords": missing},
        )

    combined = "\n".join(completed.values()).casefold()
    prohibited: list[str] = []
    for field, _hard_limit in fields:
        configured = _constraint(rulebook, field).get("prohibited_keywords", [])
        if not isinstance(configured, list) or not all(
            isinstance(item, str) for item in configured
        ):
            raise ProposalDataError(
                f"{field}.prohibited_keywords must be a string list",
                code="rulebook_invalid",
            )
        prohibited.extend(configured)
    found = [keyword for keyword in prohibited if keyword.casefold() in combined]
    if found:
        raise ProposalDataError(
            "Proposed listing contains prohibited rulebook terms",
            code="listing_invalid",
            details={"prohibited_keywords": found},
        )

    current_values = {
        "title": current.title,
        "short_description": current.short_description,
        "full_description": current.full_description,
    }
    if completed == current_values:
        raise ProposalDataError(
            "The proposed listing is identical to the live listing",
            code="listing_unchanged",
        )
    return completed


def build_store_conversion_proposal(
    *,
    package: str,
    request: StoreConversionProposalRequest,
    country_rows: Sequence[Mapping[str, Any]],
    current_listing: ListingSnapshot,
    rulebook: Mapping[str, Any],
    rulebook_source: str,
    generated_listing: ListingText | None = None,
    as_of: date | None = None,
) -> CanonicalStoreConversionProposal:
    """Build a canonical proposal without performing network or database writes."""
    validate_package_name(package)
    if not current_listing.provenance.live:
        raise ProposalDataError(
            "A verified live Play listing is required",
            code="listing_not_live",
        )
    if current_listing.language != request.language:
        raise ProposalDataError(
            "Live listing language does not match the proposal language",
            code="listing_invalid",
        )
    baseline = derive_measured_baseline(
        country_rows,
        window_days=request.baseline_window_days,
        max_source_age_days=request.max_source_age_days,
        as_of=as_of,
        locale=request.language,
    )
    listing_input = request.proposed_listing or generated_listing
    if listing_input is None:
        raise ProposalDataError("No proposed listing was generated", code="listing_missing")
    completed = validate_listing_candidate(
        listing_input, current=current_listing, rulebook=rulebook
    )
    proposal_source = "operator" if request.proposed_listing is not None else "aso_generator"
    proposed_listing = ListingSnapshot(
        **completed,
        language=request.language,
        provenance=ListingProvenance(
            source=proposal_source,
            live=False,
            retrieved_at=datetime.now(UTC),
        ),
    )
    target_value = min(1.0, baseline.value * (1 + request.target_improvement_pct))
    improvement = request.target_improvement_pct * 100
    hypothesis = (
        f"Updating the {request.language} Play listing will improve measured store view-to-install "
        f"conversion by at least {improvement:g}% from {baseline.value:.2%} to {target_value:.2%}."
    )
    experiment = ExperimentProposal(
        app_package=package,
        hypothesis=hypothesis,
        target_args={
            "packageName": package,
            "language": request.language,
            "title": completed["title"],
            "shortDescription": completed["short_description"],
            "fullDescription": completed["full_description"],
        },
        baseline_value=baseline.value,
        target_value=target_value,
        target_improvement_pct=request.target_improvement_pct,
        min_observation_days=request.min_observation_days,
        min_observation_visitors=request.min_observation_visitors,
        max_observation_days=request.max_observation_days,
        rollback_degradation_pct=request.rollback_degradation_pct,
        created_by="operator" if request.proposed_listing is not None else "aso_generator",
    )
    return CanonicalStoreConversionProposal(
        execution_mode=request.execution_mode,
        experiment=experiment,
        evidence=ProposalEvidence(
            baseline=baseline,
            current_listing=current_listing,
            proposed_listing=proposed_listing,
            rulebook=dict(rulebook),
            rulebook_source=rulebook_source,
        ),
    )


def submit_store_conversion_proposal(
    proposal: CanonicalStoreConversionProposal,
    creator: LifecycleProposalCreator,
) -> Mapping[str, Any]:
    """Submit through a lifecycle-owned callable without coupling the builder to persistence."""
    return creator(proposal.lifecycle_payload())


def make_listing_snapshot(
    *,
    title: str | None,
    short_description: str | None,
    full_description: str | None,
    language: str,
    source: str,
    live: bool,
    retrieved_at: datetime | None = None,
) -> ListingSnapshot:
    """Normalize an external listing response into evidence-ready form."""
    values = (title, short_description, full_description)
    if not all(isinstance(value, str) and value.strip() for value in values):
        raise ProposalDataError(
            "The Play Developer API returned an incomplete listing",
            code="listing_incomplete",
        )
    return ListingSnapshot(
        title=title.strip(),  # type: ignore[union-attr]
        short_description=short_description.strip(),  # type: ignore[union-attr]
        full_description=full_description.strip(),  # type: ignore[union-attr]
        language=language,
        provenance=ListingProvenance(
            source=source,
            live=live,
            retrieved_at=retrieved_at or datetime.now(UTC),
        ),
    )


ListingGenerator = Callable[[str, list[str], str, str], ListingText]


def build_keyword_rank_proposal(
    *,
    package: str,
    current_listing: ListingSnapshot,
    proposed_listing: ListingText,
    keyword: str,
    current_rank: int | None,
    language: str,
    rulebook: Mapping[str, Any],
    rulebook_source: str,
    target_tool: str = "app_store_connect/update_listing",
    min_observation_days: int = 14,
    max_observation_days: int = 28,
) -> dict[str, Any]:
    """Build a canonical aso_metadata proposal from a real App Store search-rank
    baseline instead of a conversion-rate baseline.

    For an app with too little install volume for a measured conversion-rate
    baseline to be meaningful (e.g. a brand-new listing), a real current search
    rank for a target keyword is a legitimate, measurable alternative starting
    point -- including "not ranked at all" (current_rank=None), which is itself
    a real, comparable baseline value.

    Returns a plain dict shaped for ExperimentLifecycle.create_proposal(), not
    the CanonicalStoreConversionProposal model build_store_conversion_proposal
    uses -- that model's BaselineEvidence is conversion-rate-shaped (requires
    visitors/installs/period dates), which doesn't fit rank data.
    """
    validate_package_name(package)
    if not current_listing.provenance.live:
        raise ProposalDataError("A verified live listing is required", code="listing_not_live")
    if current_listing.language != language:
        raise ProposalDataError(
            "Live listing language does not match the proposal language",
            code="listing_invalid",
        )
    completed = validate_listing_candidate(
        proposed_listing, current=current_listing, rulebook=rulebook
    )
    if completed == {
        "title": current_listing.title,
        "short_description": current_listing.short_description,
        "full_description": current_listing.full_description,
    }:
        raise ProposalDataError(
            "The proposed listing is identical to the live listing", code="listing_unchanged"
        )
    proposed_snapshot = ListingSnapshot(
        **completed,
        language=language,
        provenance=ListingProvenance(source="operator", live=False, retrieved_at=datetime.now(UTC)),
    )

    rank_label = (
        f"rank {current_rank}" if current_rank is not None else "not ranked in App Store search"
    )
    hypothesis = (
        f"Adding '{keyword}' to the {language} App Store listing will improve its App "
        f"Store search rank for '{keyword}' from {rank_label}."
    )
    now = datetime.now(UTC)
    experiment = ExperimentProposal(
        app_package=package,
        experiment_type="aso_metadata",
        hypothesis=hypothesis,
        success_metric="keyword_rank",
        target_tool=target_tool,
        target_args={
            "packageName": package,
            "language": language,
            "title": completed["title"],
            "shortDescription": completed["short_description"],
            "fullDescription": completed["full_description"],
        },
        baseline_value=float(current_rank) if current_rank is not None else 0.0,
        target_value=0.0,
        target_improvement_pct=0.0,
        min_observation_days=min_observation_days,
        min_observation_visitors=0,
        max_observation_days=max_observation_days,
        rollback_degradation_pct=0.15,
        created_by="operator",
    )
    payload = experiment.model_dump(mode="json")
    payload["evidence"] = {
        "baseline": {
            "metric": "keyword_rank",
            "keyword": keyword,
            "rank": current_rank,
            "locale": language,
            "measured_at": now.isoformat(),
            "source": "app_store_search_api",
        },
        "current_listing": current_listing.model_dump(mode="json"),
        "proposed_listing": proposed_snapshot.model_dump(mode="json"),
        "rulebook": dict(rulebook),
        "rulebook_source": rulebook_source,
    }
    payload["proposal_schema_version"] = "keyword-rank-proposal.v1"
    payload["execution_mode"] = "manual"
    return payload
