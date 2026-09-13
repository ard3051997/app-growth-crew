"""Ingest App Store Connect analytics reports (impressions, product page views,
downloads) into the local storefront database via the `asc` CLI.

Mirrors the shape of storefront_analyst.py (Play Console GCS ingestion) but the
source is Apple's real Analytics Reports API instead of GCS-exported CSVs.
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import structlog

from app_manager.credential_store import get_app_credentials
from app_store_mcp.client import AppStoreClient, AppStoreClientError
from funnel_engine.db import (
    finish_sync_run,
    init_db,
    safe_sync_error,
    save_country_performance,
    save_impressions_performance,
    start_sync_run,
)

logger = structlog.get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "store_performance.db"

# Standard (not Detailed) reports: a portfolio-level conversion metric doesn't
# need Apple's per-app-version breakdown.
PAGE_VIEWS_REPORT_NAME = "App Store Discovery and Engagement Standard"
INSTALLS_REPORT_NAME = "App Store Installation and Deletion Standard"

_ASC_TIMEOUT_SECONDS = 100


class AscAnalyticsIngestError(Exception):
    """Raised when ASC analytics ingestion cannot proceed."""


def _asc_target(package_name: str) -> tuple[str, str | None]:
    """Resolve the numeric ASC app ID and auth profile for a package."""
    creds = get_app_credentials(package_name)
    app_id = AppStoreClient()._resolve_app_id(package_name)  # noqa: SLF001
    if not app_id:
        raise AscAnalyticsIngestError(
            f"Could not resolve an App Store Connect app ID for {package_name}"
        )
    return app_id, creds.asc_profile


def _run_asc_json(args: list[str], *, profile: str | None = None) -> dict[str, Any]:
    """Run an `asc` subcommand and parse its JSON stdout.

    Raises on any failure -- never fabricates a result for a command that
    didn't run, matching AppStoreClient._run_asc's contract.
    """
    command = ["asc"]
    if profile:
        command += ["--profile", profile]
    command += args
    # Some analytics endpoints (notably `analytics view`, which scans every
    # report definition for a request) are slow enough to exceed asc's own
    # default internal context timeout -- verified live against a real ASC
    # account. ASC_TIMEOUT raises that internal deadline; the subprocess
    # timeout below is kept comfortably longer so asc's own timeout fires
    # first with a clear message instead of us killing it mid-request.
    env = {**os.environ, "ASC_TIMEOUT": "90s"}
    try:
        result = subprocess.run(  # noqa: S603 - fixed "asc" binary, no shell
            command,
            capture_output=True,
            text=True,
            timeout=_ASC_TIMEOUT_SECONDS,
            check=False,
            env=env,
        )
    except FileNotFoundError as exc:
        raise AscAnalyticsIngestError(
            "The 'asc' CLI is not installed or not on PATH (brew install asc)"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise AscAnalyticsIngestError(f"asc command timed out: {' '.join(args)}") from exc

    if result.returncode != 0:
        raise AscAnalyticsIngestError(
            f"asc command failed ({result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    if not result.stdout.strip():
        return {}
    try:
        return dict(json.loads(result.stdout))
    except json.JSONDecodeError as exc:
        raise AscAnalyticsIngestError(
            f"asc returned non-JSON output: {result.stdout[:200]}"
        ) from exc


def ensure_ongoing_request(app_id: str, *, profile: str | None = None) -> str:
    """Return an existing ONGOING analytics report request's ID, creating one if needed."""
    data = _run_asc_json(
        ["analytics", "requests", "--app", app_id, "--output", "json"], profile=profile
    )
    for row in data.get("data") or []:
        if row.get("attributes", {}).get("accessType") == "ONGOING":
            return str(row["id"])

    created = _run_asc_json(
        ["analytics", "request", "--app", app_id, "--access-type", "ONGOING", "--output", "json"],
        profile=profile,
    )
    request_id = created.get("requestId")
    if not request_id:
        raise AscAnalyticsIngestError(f"asc did not return a requestId for app {app_id}")
    return str(request_id)


def _find_report(request_id: str, report_name: str, *, profile: str | None = None) -> str | None:
    """Find a report's composite ID (e.g. 'r14-<request-id>') by exact name."""
    data = _run_asc_json(
        ["analytics", "view", "--request-id", request_id, "--output", "json"], profile=profile
    )
    for row in data.get("data") or []:
        if row.get("name") == report_name:
            return str(row["id"])
    return None


def _list_instances(report_id: str, *, profile: str | None = None) -> list[dict[str, Any]]:
    """List all report instances for a report, following pagination.

    Uses `reports view` to get the real instances URL, then `reports links
    --next <url>` to fetch it -- `reports links --report-id` rejects Apple's
    real composite report IDs with a client-side "must be a valid UUID" error
    (verified against asc 0.47.0: the bare UUID reaches the server fine, so
    this is a CLI-side over-strict regex, not a real API constraint). Passing
    the full URL via --next sidesteps that validator entirely.
    """
    report = _run_asc_json(
        ["analytics", "reports", "view", "--report-id", report_id, "--output", "json"],
        profile=profile,
    )
    next_url = (
        report.get("data", {})
        .get("relationships", {})
        .get("instances", {})
        .get("links", {})
        .get("related")
    )
    instances: list[dict[str, Any]] = []
    while next_url:
        page = _run_asc_json(
            ["analytics", "reports", "links", "--next", next_url, "--output", "json"],
            profile=profile,
        )
        instances.extend(page.get("data") or [])
        next_url = page.get("links", {}).get("next")
    return instances


def _list_segments(instance_id: str, *, profile: str | None = None) -> list[str]:
    """List segment IDs for an instance; empty means a single unsegmented file."""
    data = _run_asc_json(
        ["analytics", "instances", "links", "--instance-id", instance_id, "--output", "json"],
        profile=profile,
    )
    return [str(row["id"]) for row in (data.get("data") or []) if row.get("id")]


def _download_segment(
    request_id: str,
    instance_id: str,
    *,
    segment_id: str | None = None,
    profile: str | None = None,
    tmp_dir: Path,
) -> str:
    """Download and decompress one report segment, returning its CSV text."""
    output_path = tmp_dir / f"{request_id}_{instance_id}_{segment_id or 'single'}.csv"
    args = [
        "analytics",
        "download",
        "--request-id",
        request_id,
        "--instance-id",
        instance_id,
        "--decompress",
        "--output",
        str(output_path),
    ]
    if segment_id:
        args += ["--segment-id", segment_id]
    _run_asc_json(args, profile=profile)
    if not output_path.is_file():
        raise AscAnalyticsIngestError(f"asc download did not produce {output_path}")
    try:
        return output_path.read_text(encoding="utf-8", errors="replace")
    finally:
        output_path.unlink(missing_ok=True)


def download_instance_csv(
    request_id: str,
    instance_id: str,
    *,
    profile: str | None = None,
    tmp_dir: Path,
) -> list[str]:
    """Download every segment of a report instance and return the raw CSV texts."""
    segment_ids = _list_segments(instance_id, profile=profile)
    if not segment_ids:
        return [_download_segment(request_id, instance_id, profile=profile, tmp_dir=tmp_dir)]
    return [
        _download_segment(
            request_id, instance_id, segment_id=segment_id, profile=profile, tmp_dir=tmp_dir
        )
        for segment_id in segment_ids
    ]


def _parse_csv_content(content: str) -> list[list[str]]:
    """Clean and parse CSV/TSV text, handling a BOM and either delimiter."""
    if not content:
        return []
    if content.startswith("﻿"):
        content = content[1:]
    lines = content.splitlines()
    if not lines:
        return []
    delimiter = "\t" if lines[0].count("\t") > lines[0].count(",") else ","
    return list(csv.reader(lines, delimiter=delimiter))


def _find_column(col_indices: dict[str, int], *markers: str) -> int | None:
    for col, idx in col_indices.items():
        lowered = col.lower()
        if all(marker in lowered for marker in markers):
            return idx
    return None


def _to_int(value: str) -> int | None:
    try:
        return int(value.replace(",", "").replace("\xa0", "").strip())
    except ValueError:
        return None


def parse_metric_rows(
    rows: list[list[str]], *, metric_markers: tuple[str, ...], exclude: tuple[str, ...] = ()
) -> dict[tuple[str, str], int]:
    """Aggregate an Apple analytics CSV into {(date, territory): metric_total}.

    Handles two plausible export shapes since no live sample was available to
    confirm which one Apple actually uses for these reports:
      - "wide": a distinct numeric column whose header matches metric_markers.
      - "tidy/long": a categorical Event/Metric column plus one numeric
        Counts/Value column, filtered by matching the event text.
    Returns {} (and logs a warning) rather than guessing when neither shape
    is recognized -- this must never fabricate a row.
    """
    if not rows:
        return {}
    header = [col.strip() for col in rows[0]]
    col_indices = {col: idx for idx, col in enumerate(header)}
    data_rows = rows[1:]

    date_idx = _find_column(col_indices, "date")
    territory_idx = _find_column(col_indices, "territory") or _find_column(col_indices, "country")
    if date_idx is None or territory_idx is None:
        logger.warning("ASC report missing date/territory columns", header=header)
        return {}

    totals: dict[tuple[str, str], int] = {}

    wide_idx = _find_column(col_indices, *metric_markers)
    if wide_idx is not None and not any(
        _find_column(col_indices, marker) is not None for marker in ("event", "metric")
    ):
        for row in data_rows:
            if len(row) <= max(date_idx, territory_idx, wide_idx):
                continue
            observed_on = _normalize_report_date(row[date_idx])
            value = _to_int(row[wide_idx])
            if observed_on is None or value is None:
                continue
            key = (observed_on, row[territory_idx].strip())
            totals[key] = totals.get(key, 0) + value
        return totals

    event_idx = _find_column(col_indices, "event") or _find_column(col_indices, "metric")
    value_idx = _find_column(col_indices, "count") or _find_column(col_indices, "value")
    if event_idx is not None and value_idx is not None:
        for row in data_rows:
            if len(row) <= max(date_idx, territory_idx, event_idx, value_idx):
                continue
            event_text = row[event_idx].strip().lower()
            if any(marker in event_text for marker in exclude):
                continue
            if not any(marker in event_text for marker in metric_markers):
                continue
            observed_on = _normalize_report_date(row[date_idx])
            value = _to_int(row[value_idx])
            if observed_on is None or value is None:
                continue
            key = (observed_on, row[territory_idx].strip())
            totals[key] = totals.get(key, 0) + value
        return totals

    logger.warning(
        "ASC report did not match a recognized wide or tidy shape",
        header=header,
        metric_markers=metric_markers,
    )
    return {}


def _normalize_report_date(value: str) -> str | None:
    try:
        return date.fromisoformat(value.strip()[:10]).isoformat()
    except ValueError:
        return None


def ingest_asc_reports(
    package_name: str,
    db_path: Path = DEFAULT_DB_PATH,
    *,
    tmp_dir: Path | None = None,
) -> dict[str, Any]:
    """Fetch and ingest all available ASC analytics report instances for one app."""
    init_db(db_path)
    run_id = start_sync_run(db_path, "asc_analytics", package_name)
    try:
        app_id, profile = _asc_target(package_name)
        request_id = ensure_ongoing_request(app_id, profile=profile)

        page_view_totals: dict[tuple[str, str], int] = {}
        install_totals: dict[tuple[str, str], int] = {}
        impression_totals: dict[tuple[str, str], int] = {}
        instances_processed = 0

        with tempfile.TemporaryDirectory() as tmp:
            work_dir = tmp_dir or Path(tmp)

            page_view_report_id = _find_report(request_id, PAGE_VIEWS_REPORT_NAME, profile=profile)
            if page_view_report_id:
                for instance in _list_instances(page_view_report_id, profile=profile):
                    for content in download_instance_csv(
                        request_id, str(instance["id"]), profile=profile, tmp_dir=work_dir
                    ):
                        rows = _parse_csv_content(content)
                        for key, value in parse_metric_rows(
                            rows, metric_markers=("impression",)
                        ).items():
                            impression_totals[key] = impression_totals.get(key, 0) + value
                        for key, value in parse_metric_rows(
                            rows, metric_markers=("page", "view")
                        ).items():
                            page_view_totals[key] = page_view_totals.get(key, 0) + value
                        instances_processed += 1

            installs_report_id = _find_report(request_id, INSTALLS_REPORT_NAME, profile=profile)
            if installs_report_id:
                for instance in _list_instances(installs_report_id, profile=profile):
                    for content in download_instance_csv(
                        request_id, str(instance["id"]), profile=profile, tmp_dir=work_dir
                    ):
                        rows = _parse_csv_content(content)
                        for key, value in parse_metric_rows(
                            rows, metric_markers=("download",), exclude=("delet",)
                        ).items():
                            install_totals[key] = install_totals.get(key, 0) + value
                        instances_processed += 1

        persisted_dates: set[str] = set()
        total_records = 0
        country_keys = set(page_view_totals) | set(install_totals)
        for observed_on, territory in country_keys:
            visitors = page_view_totals.get((observed_on, territory), 0)
            installs = install_totals.get((observed_on, territory), 0)
            rate = (installs / visitors) if visitors > 0 else 0.0
            save_country_performance(
                db_path, observed_on, package_name, territory, visitors, installs, rate
            )
            persisted_dates.add(observed_on)
            total_records += 1
        for (observed_on, territory), impressions in impression_totals.items():
            save_impressions_performance(db_path, observed_on, package_name, territory, impressions)
            persisted_dates.add(observed_on)
            total_records += 1

        status = "success" if total_records > 0 else "partial"
        error_safe = (
            None if total_records > 0 else "No analytics report instances are available yet"
        )
        period_start = min(persisted_dates) if persisted_dates else None
        period_end = max(persisted_dates) if persisted_dates else None
        finish_sync_run(
            db_path,
            run_id,
            status,
            record_count=total_records,
            period_start=period_start,
            period_end=period_end,
            error_safe=error_safe,
            metadata_json=json.dumps({"instances_processed": instances_processed}),
        )
        return {
            "success": True,
            "status": status,
            "package_name": package_name,
            "records_inserted": total_records,
            "instances_processed": instances_processed,
            "period_start": period_start,
            "period_end": period_end,
        }
    except (AscAnalyticsIngestError, AppStoreClientError) as exc:
        finish_sync_run(
            db_path,
            run_id,
            "failure",
            error_safe=safe_sync_error(exc, "ASC analytics sync unavailable"),
        )
        return {
            "success": False,
            "status": "failure",
            "package_name": package_name,
            "error": str(exc),
        }
    except Exception as exc:
        finish_sync_run(
            db_path,
            run_id,
            "failure",
            error_safe=safe_sync_error(exc, "ASC analytics sync unavailable"),
        )
        raise
