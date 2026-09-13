"""Subagent logic to download, parse, and ingest storefront performance CSV files from GCS into SQLite."""

from __future__ import annotations

import csv
import json
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import structlog

from app_manager.config import AppManagerConfig
from app_manager.credential_store import get_app_credentials
from funnel_engine.db import (
    finish_sync_run,
    get_country_performance,
    get_search_performance,
    get_traffic_performance,
    init_db,
    safe_sync_error,
    save_country_performance,
    save_search_performance,
    save_traffic_performance,
    start_sync_run,
)
from gcs_mcp.client import GCSClient

logger = structlog.get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "store_performance.db"
DEFAULT_JSON_EXPORT_PATH = PROJECT_ROOT / "data" / "storefront_conversion_history.json"


def _storefront_config(package_name: str) -> AppManagerConfig:
    """Resolve GCS and Google credentials for the app being ingested."""
    credentials = get_app_credentials(package_name)
    return AppManagerConfig(
        package_name=package_name,
        google_credentials_path=credentials.google_credentials_path,
        gcs_play_console_bucket=credentials.gcs_play_console_bucket,
    )


def _current_and_previous_month(now: datetime) -> list[str]:
    """Return distinct current and prior calendar months in newest-first order."""
    previous_month = now.replace(day=1) - timedelta(days=1)
    return [now.strftime("%Y%m"), previous_month.strftime("%Y%m")]


def _get_gcs_client(config: AppManagerConfig) -> GCSClient:
    """Initialize GCS client using configured credentials."""
    if not config.google_credentials_path:
        raise ValueError("GOOGLE_APPLICATION_CREDENTIALS path is not configured.")

    try:
        with Path(config.google_credentials_path).open() as f:
            creds = json.load(f)
        return GCSClient(credentials_json=creds)
    except Exception as e:
        logger.exception("Failed to initialize GCS client", error=str(e))
        raise ValueError(f"Failed to initialize GCS client: {e}") from e


def parse_csv_content(content: str) -> list[list[str]]:
    """Clean and parse CSV text, handling UTF-16 BOM and varying newline delimiters."""
    if not content:
        return []

    # Remove BOM if present
    if content.startswith("\ufeff"):
        content = content[1:]

    lines = content.splitlines()
    reader = csv.reader(lines)
    return list(reader)


def _normalize_report_date(value: str) -> str | None:
    """Validate a report date and return its canonical ISO calendar representation."""
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError:
        return None


def ingest_csv_data(
    package_name: str,
    file_type: str,  # "country" or "traffic_source"
    rows: list[list[str]],
    db_path: Path = DEFAULT_DB_PATH,
    persisted_dates: set[str] | None = None,
) -> int:
    """Idempotently parse and insert CSV rows into database."""
    if not rows:
        return 0

    header = [col.strip() for col in rows[0]]
    col_indices = {col: idx for idx, col in enumerate(header)}
    data_rows = rows[1:]

    visitors_col = next(
        (c for c in col_indices if "visitor" in c.lower() or "view" in c.lower()), None
    )
    acquisitions_col = next(
        (c for c in col_indices if "acquisition" in c.lower() or "install" in c.lower()), None
    )

    if not visitors_col or not acquisitions_col:
        logger.warning("Missing required columns in CSV header", header=header)
        return 0

    v_idx = col_indices[visitors_col]
    a_idx = col_indices[acquisitions_col]

    date_col = next((c for c in col_indices if "date" in c.lower()), None)
    date_idx = col_indices[date_col] if date_col else 0

    inserted_count = 0

    if file_type == "country":
        country_col = next((c for c in col_indices if "country" in c.lower()), None)
        if not country_col:
            logger.warning("Country column not found in country report", header=header)
            return 0
        c_idx = col_indices[country_col]

        for row in data_rows:
            if len(row) <= max(date_idx, c_idx, v_idx, a_idx):
                continue
            date_val = _normalize_report_date(row[date_idx])
            if date_val is None:
                continue
            country = row[c_idx].strip()
            try:
                visitors = int(row[v_idx].replace(",", "").replace("\xa0", "").strip())
                installs = int(row[a_idx].replace(",", "").replace("\xa0", "").strip())
            except ValueError:
                continue

            rate = (installs / visitors) if visitors > 0 else 0.0
            save_country_performance(
                db_path, date_val, package_name, country, visitors, installs, rate
            )
            if persisted_dates is not None:
                persisted_dates.add(date_val)
            inserted_count += 1

    elif file_type == "traffic_source":
        traffic_col = next(
            (c for c in col_indices if "traffic" in c.lower() or "source" in c.lower()), None
        )
        term_col = next(
            (c for c in col_indices if "search" in c.lower() or "term" in c.lower()), None
        )

        if not traffic_col:
            logger.warning("Traffic source column not found in traffic report", header=header)
            return 0
        t_idx = col_indices[traffic_col]
        term_idx = col_indices[term_col] if term_col else None

        for row in data_rows:
            if len(row) <= max(date_idx, t_idx, v_idx, a_idx):
                continue
            date_val = _normalize_report_date(row[date_idx])
            if date_val is None:
                continue
            source = row[t_idx].strip()
            try:
                visitors = int(row[v_idx].replace(",", "").replace("\xa0", "").strip())
                installs = int(row[a_idx].replace(",", "").replace("\xa0", "").strip())
            except ValueError:
                continue

            rate = (installs / visitors) if visitors > 0 else 0.0

            # If search term is present, also log search term performance
            if term_idx is not None and len(row) > term_idx:
                term = row[term_idx].strip()
                if term:
                    save_search_performance(
                        db_path, date_val, package_name, term, visitors, installs, rate
                    )
                    if persisted_dates is not None:
                        persisted_dates.add(date_val)

            save_traffic_performance(
                db_path, date_val, package_name, source, visitors, installs, rate
            )
            if persisted_dates is not None:
                persisted_dates.add(date_val)
            inserted_count += 1

    return inserted_count


def export_db_to_json(
    package_name: str,
    db_path: Path = DEFAULT_DB_PATH,
    export_path: Path = DEFAULT_JSON_EXPORT_PATH,
) -> None:
    """Export historical database performance records to a static JSON file for the JMIP UI."""
    logger.info("Exporting storefront metrics database to JSON", export_path=str(export_path))
    try:
        countries = get_country_performance(db_path, package_name)
        traffic_sources = get_traffic_performance(db_path, package_name)
        search_terms = get_search_performance(db_path, package_name)

        data = {
            "package_name": package_name,
            "exported_at": datetime.now().isoformat(),
            "country_performance": countries,
            "traffic_source_performance": traffic_sources,
            "search_term_performance": search_terms,
        }

        export_path.parent.mkdir(parents=True, exist_ok=True)
        with export_path.open("w") as f:
            json.dump(data, f, indent=2)
        logger.info("JSON metrics export completed successfully")
    except Exception as e:
        logger.exception("Failed to export metrics to JSON", error=str(e))


async def ingest_latest_month(
    package_name: str,
    db_path: Path = DEFAULT_DB_PATH,
    export_path: Path = DEFAULT_JSON_EXPORT_PATH,
) -> dict[str, Any]:
    """Fetch and ingest GCS reports for the current and previous month."""
    init_db(db_path)
    run_id = start_sync_run(db_path, "storefront", package_name)
    try:
        config = _storefront_config(package_name)
        if not config.gcs_play_console_bucket:
            raise ValueError("Storefront report source is not configured")

        gcs = _get_gcs_client(config)
        bucket = config.gcs_play_console_bucket
        months = _current_and_previous_month(datetime.now(UTC))
        expected_files = len(months) * 2
        ingested_files = []
        failed_files = []
        total_inserted = 0
        current_run_dates: set[str] = set()

        for month in months:
            for file_type in ["country", "traffic_source"]:
                blob_name = (
                    "stats/store_performance/"
                    f"store_performance_{package_name}_{month}_{file_type}.csv"
                )
                logger.info("Downloading file from GCS", bucket=bucket, blob=blob_name)
                try:
                    content = gcs.read_blob_content(bucket, blob_name)
                    rows = parse_csv_content(content)
                    inserted = ingest_csv_data(
                        package_name,
                        file_type,
                        rows,
                        db_path,
                        persisted_dates=current_run_dates,
                    )
                    if inserted <= 0:
                        raise ValueError("Storefront report contained no valid data rows")
                    logger.info("Ingested CSV records", file=blob_name, records=inserted)
                    ingested_files.append(blob_name)
                    total_inserted += inserted
                except Exception as exc:
                    failed_files.append(blob_name)
                    logger.warning(
                        "Storefront report file unavailable",
                        file=blob_name,
                        error_type=type(exc).__name__,
                    )

        period_start = min(current_run_dates) if current_run_dates else None
        period_end = max(current_run_dates) if current_run_dates else None
        if len(ingested_files) == expected_files:
            status = "success"
            error_safe = None
        elif ingested_files:
            status = "partial"
            error_safe = f"{len(failed_files)} expected storefront report file(s) unavailable"
        else:
            status = "failure"
            error_safe = "No expected storefront report files were available"
        finish_sync_run(
            db_path,
            run_id,
            status,
            record_count=total_inserted,
            period_start=period_start,
            period_end=period_end,
            error_safe=error_safe,
            metadata_json=json.dumps(
                {"files_read": len(ingested_files), "files_expected": expected_files}
            ),
        )
        if ingested_files:
            export_db_to_json(package_name, db_path, export_path)
        return {
            "success": status in {"success", "partial"},
            "status": status,
            "package_name": package_name,
            "ingested_files": ingested_files,
            "failed_files": failed_files,
            "records_inserted": total_inserted,
            "period_start": period_start,
            "period_end": period_end,
        }
    except Exception as exc:
        finish_sync_run(
            db_path,
            run_id,
            "failure",
            error_safe=safe_sync_error(exc, "Storefront sync unavailable"),
        )
        raise


async def backfill_history(
    package_name: str,
    db_path: Path = DEFAULT_DB_PATH,
    export_path: Path = DEFAULT_JSON_EXPORT_PATH,
) -> dict[str, Any]:
    """Iterate through all historical store performance CSV files in GCS and ingest them."""
    init_db(db_path)
    run_id = start_sync_run(db_path, "storefront_backfill", package_name)
    try:
        config = _storefront_config(package_name)
        if not config.gcs_play_console_bucket:
            raise ValueError("Storefront report source is not configured")

        gcs = _get_gcs_client(config)
        bucket = config.gcs_play_console_bucket
        logger.info("Fetching list of all blobs in GCS", bucket=bucket)
        blobs = gcs.list_blobs(bucket, prefix="stats/store_performance/")
        country_regex = re.compile(
            rf"stats/store_performance/store_performance_{package_name}_(\d{{6}})_country\.csv"
        )
        traffic_regex = re.compile(
            rf"stats/store_performance/store_performance_{package_name}_(\d{{6}})_traffic_source\.csv"
        )
        ingested_files = []
        failed_count = 0
        total_inserted = 0

        for blob in blobs:
            blob_name = blob["name"]
            file_type = None
            if country_regex.match(blob_name):
                file_type = "country"
            elif traffic_regex.match(blob_name):
                file_type = "traffic_source"
            if not file_type:
                continue
            try:
                content = gcs.read_blob_content(bucket, blob_name)
                rows = parse_csv_content(content)
                inserted = ingest_csv_data(package_name, file_type, rows, db_path)
                if inserted <= 0:
                    raise ValueError("Storefront report contained no valid data rows")
                ingested_files.append(blob_name)
                total_inserted += inserted
            except Exception as exc:
                failed_count += 1
                logger.warning(
                    "Storefront backfill file unavailable",
                    file=blob_name,
                    error_type=type(exc).__name__,
                )

        status = "partial" if failed_count and ingested_files else "success"
        if not ingested_files:
            status = "failure"
        error_safe = (
            f"{failed_count} storefront backfill file(s) unavailable" if failed_count else None
        )
        finish_sync_run(
            db_path,
            run_id,
            status,
            record_count=total_inserted,
            error_safe=error_safe,
        )
        if ingested_files:
            export_db_to_json(package_name, db_path, export_path)
        return {
            "success": status in {"success", "partial"},
            "status": status,
            "package_name": package_name,
            "ingested_files_count": len(ingested_files),
            "records_inserted": total_inserted,
        }
    except Exception as exc:
        finish_sync_run(
            db_path,
            run_id,
            "failure",
            error_safe=safe_sync_error(exc, "Storefront backfill unavailable"),
        )
        raise
