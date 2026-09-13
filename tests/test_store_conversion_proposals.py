"""Store-conversion proposal data quality and API integration tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from api_server.main import app
from api_server.routes import apps, experiments
from app_manager.credential_store import AppCredentials
from app_manager.experiment_lifecycle import ExperimentLifecycle
from app_manager.experiment_validation import validate_experiment
from app_manager.store_conversion_proposals import (
    ListingText,
    ProposalDataError,
    StoreConversionProposalRequest,
    build_keyword_rank_proposal,
    build_store_conversion_proposal,
    derive_measured_baseline,
    load_rulebook,
    make_listing_snapshot,
    redact_rulebook,
)
from app_manager.storefront_analyst import _current_and_previous_month, _storefront_config
from funnel_engine.db import init_db

if TYPE_CHECKING:
    from pathlib import Path


def _country_rows(end: date, days: int = 7) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for offset in range(days):
        observed_on = end - timedelta(days=days - offset - 1)
        rows.extend(
            [
                {
                    "date": observed_on.isoformat(),
                    "country": "US",
                    "visitors": 100,
                    "installs": 10,
                },
                {
                    "date": observed_on.isoformat(),
                    "country": "IN",
                    "visitors": 20,
                    "installs": 10,
                },
            ]
        )
    return rows


def _rulebook() -> dict[str, Any]:
    return {
        "package_name": "com.example.app",
        "metadata_constraints": {
            "title": {
                "max_length": 50,
                "required_keywords": ["Example", "Loan"],
            },
            "short_description": {"max_length": 80},
            "full_description": {
                "max_length": 4000,
                "prohibited_keywords": ["instant payout"],
            },
        },
        "aso_strategy": {"target_keywords": ["loan calculator"]},
    }


def _live_listing():
    return make_listing_snapshot(
        title="Example Loan",
        short_description="A measured loan calculator for everyday planning.",
        full_description="Plan repayments with clear calculator results.",
        language="en-US",
        source="google_play_developer_api",
        live=True,
        retrieved_at=datetime(2026, 7, 20, tzinfo=UTC),
    )


def test_baseline_is_complete_daily_and_visitor_weighted() -> None:
    baseline = derive_measured_baseline(
        _country_rows(date(2026, 7, 20)),
        as_of=date(2026, 7, 20),
    )

    assert baseline.observed_days == 7
    assert baseline.completeness_ratio == 1.0
    assert baseline.visitors == 840
    assert baseline.installs == 140
    assert baseline.value == pytest.approx(1 / 6)
    assert baseline.daily[0].country_rows == 2
    assert baseline.measured is True
    assert baseline.synthetic is False


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda rows: rows[:-2], "baseline_incomplete"),
        (lambda rows: [dict(rows[0], synthetic=True), *rows[1:]], "baseline_synthetic"),
    ],
)
def test_baseline_rejects_incomplete_and_synthetic_rows(mutate, code: str) -> None:
    rows = mutate(_country_rows(date(2026, 7, 20)))
    with pytest.raises(ProposalDataError) as raised:
        derive_measured_baseline(rows, as_of=date(2026, 7, 20))
    assert raised.value.code == code


def test_baseline_rejects_stale_source() -> None:
    with pytest.raises(ProposalDataError) as raised:
        derive_measured_baseline(
            _country_rows(date(2026, 7, 10)),
            as_of=date(2026, 7, 20),
            max_source_age_days=3,
        )
    assert raised.value.code == "baseline_stale"
    assert raised.value.details["source_age_days"] == 10


def test_pure_builder_constructs_canonical_lifecycle_evidence() -> None:
    request = StoreConversionProposalRequest(
        proposed_listing=ListingText(title="Example Loan Planner")
    )
    proposal = build_store_conversion_proposal(
        package="com.example.app",
        request=request,
        country_rows=_country_rows(date(2026, 7, 20)),
        current_listing=_live_listing(),
        rulebook=_rulebook(),
        rulebook_source="rulebooks/com.example.app.yaml",
        as_of=date(2026, 7, 20),
    )
    payload = proposal.lifecycle_payload()

    assert payload["baseline_value"] == pytest.approx(1 / 6)
    assert payload["target_args"]["packageName"] == "com.example.app"
    assert payload["target_args"]["shortDescription"] == _live_listing().short_description
    assert payload["evidence"]["baseline"]["source"] == "play_console_gcs_store_performance"
    assert payload["evidence"]["current_listing"]["provenance"]["live"] is True
    assert payload["evidence"]["proposed_listing"]["provenance"]["source"] == "operator"
    assert payload["execution_mode"] == "manual"
    validation = validate_experiment(
        payload,
        evidence=payload["evidence"],
        rulebook=_rulebook(),
        now=datetime(2026, 7, 20, 12, tzinfo=UTC),
    )
    assert validation["valid"] is True


def test_builder_enforces_rulebook_terms() -> None:
    request = StoreConversionProposalRequest(
        proposed_listing=ListingText(
            title="Example Planner",
            full_description="Get an instant payout.",
        )
    )
    with pytest.raises(ProposalDataError) as raised:
        build_store_conversion_proposal(
            package="com.example.app",
            request=request,
            country_rows=_country_rows(date(2026, 7, 20)),
            current_listing=_live_listing(),
            rulebook=_rulebook(),
            rulebook_source="rulebooks/com.example.app.yaml",
            as_of=date(2026, 7, 20),
        )
    assert raised.value.code == "listing_invalid"


def test_keyword_rank_builder_constructs_canonical_lifecycle_evidence() -> None:
    payload = build_keyword_rank_proposal(
        package="com.example.app",
        current_listing=_live_listing(),
        proposed_listing=ListingText(title="Example Loan Calculator"),
        keyword="loan calculator",
        current_rank=None,
        language="en-US",
        rulebook=_rulebook(),
        rulebook_source="rulebooks/com.example.app.yaml",
    )

    assert payload["success_metric"] == "keyword_rank"
    assert payload["experiment_type"] == "aso_metadata"
    assert payload["target_tool"] == "app_store_connect/update_listing"
    assert payload["baseline_value"] == 0.0
    assert payload["execution_mode"] == "manual"
    assert payload["evidence"]["baseline"]["metric"] == "keyword_rank"
    assert payload["evidence"]["baseline"]["keyword"] == "loan calculator"
    assert payload["evidence"]["baseline"]["rank"] is None
    assert payload["evidence"]["baseline"]["source"] == "app_store_search_api"
    assert payload["evidence"]["current_listing"]["provenance"]["live"] is True
    assert payload["evidence"]["proposed_listing"]["provenance"]["source"] == "operator"
    assert "not ranked" in payload["hypothesis"]

    validation = validate_experiment(
        payload,
        evidence=payload["evidence"],
        rulebook=_rulebook(),
        executable_locale="en-US",
        now=datetime.now(UTC),
    )
    assert validation["valid"] is True


def test_keyword_rank_builder_accepts_a_measured_rank() -> None:
    payload = build_keyword_rank_proposal(
        package="com.example.app",
        current_listing=_live_listing(),
        proposed_listing=ListingText(title="Example Loan Calculator"),
        keyword="loan calculator",
        current_rank=138,
        language="en-US",
        rulebook=_rulebook(),
        rulebook_source="rulebooks/com.example.app.yaml",
    )

    assert payload["baseline_value"] == 138.0
    assert payload["evidence"]["baseline"]["rank"] == 138
    assert "rank 138" in payload["hypothesis"]


def test_keyword_rank_builder_rejects_an_unchanged_listing() -> None:
    live = _live_listing()
    with pytest.raises(ProposalDataError) as raised:
        build_keyword_rank_proposal(
            package="com.example.app",
            current_listing=live,
            proposed_listing=ListingText(title=live.title),
            keyword="loan calculator",
            current_rank=None,
            language="en-US",
            rulebook=_rulebook(),
            rulebook_source="rulebooks/com.example.app.yaml",
        )
    assert raised.value.code == "listing_unchanged"


def test_keyword_rank_builder_enforces_rulebook_terms() -> None:
    with pytest.raises(ProposalDataError) as raised:
        build_keyword_rank_proposal(
            package="com.example.app",
            current_listing=_live_listing(),
            proposed_listing=ListingText(
                title="Example Loan", full_description="Get an instant payout."
            ),
            keyword="loan calculator",
            current_rank=None,
            language="en-US",
            rulebook=_rulebook(),
            rulebook_source="rulebooks/com.example.app.yaml",
        )
    assert raised.value.code == "listing_invalid"


def test_keyword_rank_builder_rejects_a_non_live_listing() -> None:
    stale = make_listing_snapshot(
        title="Example Loan",
        short_description="A measured loan calculator for everyday planning.",
        full_description="Plan repayments with clear calculator results.",
        language="en-US",
        source="operator",
        live=False,
    )
    with pytest.raises(ProposalDataError) as raised:
        build_keyword_rank_proposal(
            package="com.example.app",
            current_listing=stale,
            proposed_listing=ListingText(title="Example Loan Calculator"),
            keyword="loan calculator",
            current_rank=None,
            language="en-US",
            rulebook=_rulebook(),
            rulebook_source="rulebooks/com.example.app.yaml",
        )
    assert raised.value.code == "listing_not_live"


def test_rulebook_loader_is_package_bound_and_redacts_secrets(tmp_path: Path) -> None:
    rulebooks = tmp_path / "rulebooks"
    rulebooks.mkdir()
    path = rulebooks / "com.example.app.yaml"
    path.write_text(
        "package_name: com.example.app\napi_token: hidden\nmetadata_constraints: {}\n",
        encoding="utf-8",
    )

    rulebook, loaded_path = load_rulebook("com.example.app", project_root=tmp_path)
    assert loaded_path == path
    assert redact_rulebook(rulebook)["api_token"] == "********"
    with pytest.raises(ProposalDataError, match="Invalid app package"):
        load_rulebook("../outside", project_root=tmp_path)


def test_proposal_endpoint_uses_operator_listing_and_lifecycle_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rulebooks = tmp_path / "rulebooks"
    rulebooks.mkdir()
    (rulebooks / "com.example.app.yaml").write_text(
        """package_name: com.example.app
metadata_constraints:
  title:
    max_length: 50
    required_keywords: [Example, Loan]
  short_description:
    max_length: 80
  full_description:
    max_length: 4000
aso_strategy:
  target_keywords: [loan calculator]
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(apps, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(apps, "_get_live_play_listing", lambda *_args: _live_listing())
    monkeypatch.setattr(
        apps,
        "get_country_performance",
        lambda *_args: _country_rows(datetime.now(UTC).date()),
    )
    lifecycle = MagicMock(return_value={"id": "exp-123", "evidence_persisted": True})
    monkeypatch.setattr(apps, "_create_via_experiment_lifecycle", lifecycle)

    with TestClient(app) as client:
        response = client.post(
            "/api/apps/com.example.app/store-conversion/proposals",
            json={"proposed_listing": {"title": "Example Loan Planner"}},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["experiment"]["id"] == "exp-123"
    assert body["proposal"]["execution_mode"] == "manual"
    assert body["auto_executed"] is False
    assert body["requires_review"] is True
    assert body["proposal"]["experiment"]["baseline_value"] == pytest.approx(1 / 6)
    submitted = lifecycle.call_args.args[0]
    assert submitted["evidence"]["baseline"]["observed_days"] == 7
    assert submitted["target_args"]["title"] == "Example Loan Planner"

    with TestClient(app) as client:
        rejected = client.post(
            "/api/apps/com.example.app/store-conversion/proposals",
            json={
                "app_package": "com.attacker.supplied",
                "target_tool": "play_store/update_listing",
                "proposed_listing": {"title": "Example Loan Planner"},
            },
        )
    assert rejected.status_code == 422


@pytest.mark.parametrize(
    ("mode", "expected_status", "expected_writes", "requires_review"),
    [
        ("recommend_only", "proposed", 0, False),
        ("manual", "proposed", 0, True),
        ("auto_low_risk", "measuring", 1, False),
    ],
)
def test_proposal_endpoint_integrates_execution_modes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    expected_status: str,
    expected_writes: int,
    requires_review: bool,
) -> None:
    rulebooks = tmp_path / "rulebooks"
    rulebooks.mkdir()
    (rulebooks / "com.example.app.yaml").write_text(
        """package_name: com.example.app
metadata_constraints:
  title:
    max_length: 30
    required_keywords: [Example, Loan]
  short_description:
    max_length: 80
  full_description:
    max_length: 4000
aso_strategy:
  target_keywords: [loan calculator]
""",
        encoding="utf-8",
    )
    db_path = tmp_path / "experiments.sqlite"
    init_db(db_path)
    listing = _live_listing().model_dump(mode="json")
    writes: list[dict[str, Any]] = []

    def write_listing(_package: str, args: dict[str, Any]) -> dict[str, bool]:
        writes.append(args)
        listing["title"] = args["title"]
        listing["short_description"] = args["shortDescription"]
        listing["full_description"] = args["fullDescription"]
        return {"success": True}

    lifecycle = ExperimentLifecycle(
        db_path,
        rulebook_dir=rulebooks,
        listing_reader=lambda *_args: dict(listing),
        listing_writer=write_listing,
    )
    monkeypatch.setattr(apps, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(apps, "_get_live_play_listing", lambda *_args: _live_listing())
    monkeypatch.setattr(
        apps,
        "get_country_performance",
        lambda *_args: _country_rows(datetime.now(UTC).date()),
    )
    monkeypatch.setattr(experiments, "_service", lambda: lifecycle)

    with TestClient(app) as client:
        response = client.post(
            "/api/apps/com.example.app/store-conversion/proposals",
            json={
                "execution_mode": mode,
                "proposed_listing": {"title": "Example Loan Planner"},
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["experiment"]["status"] == expected_status
    assert body["experiment"]["autonomy_mode"] == mode
    assert body["validation"]["valid"] is True
    assert body["requires_review"] is requires_review
    assert body["auto_executed"] is (mode == "auto_low_risk")
    assert len(writes) == expected_writes


def test_rulebook_endpoint_returns_redacted_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rulebooks = tmp_path / "rulebooks"
    rulebooks.mkdir()
    (rulebooks / "com.example.app.yaml").write_text(
        "package_name: com.example.app\napi_key: secret\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(apps, "PROJECT_ROOT", tmp_path)

    with TestClient(app) as client:
        response = client.get("/api/apps/com.example.app/rulebook")

    assert response.status_code == 200
    assert response.json()["raw_rulebook"]["api_key"] == "********"
    assert response.json()["provenance"] == {
        "source": "rulebooks/com.example.app.yaml",
        "is_live": False,
        "captured_at": None,
        "reference": "com.example.app",
    }


def test_listing_endpoint_labels_unavailable_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        apps,
        "get_app_credentials",
        lambda package: AppCredentials(package_name=package),
    )
    with TestClient(app) as client:
        response = client.get("/api/apps/com.example.app/listing/en-US")

    assert response.status_code == 200
    assert response.json()["status"] == "unavailable"
    assert response.json()["title"] is None
    assert response.json()["provenance"]["source"] == "unavailable"
    assert response.json()["provenance"]["live"] is False


def test_storefront_month_rollover_and_per_app_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _current_and_previous_month(datetime(2026, 1, 15, tzinfo=UTC)) == ["202601", "202512"]
    credentials = SimpleNamespace(
        google_credentials_path="/app/key.json",
        gcs_play_console_bucket="app-specific-bucket",
    )
    monkeypatch.setattr(
        "app_manager.storefront_analyst.get_app_credentials",
        lambda package: credentials if package == "com.example.app" else None,
    )

    config = _storefront_config("com.example.app")
    assert config.package_name == "com.example.app"
    assert config.google_credentials_path == "/app/key.json"
    assert config.gcs_play_console_bucket == "app-specific-bucket"
