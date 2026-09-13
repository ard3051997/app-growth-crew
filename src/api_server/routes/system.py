"""System status and locally persisted operator configuration routes."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api_server.auth import config_writes_enabled, env_enabled
from api_server.routes.portfolio import get_latest_system_trust
from app_manager.credential_store import PROJECT_ROOT
from funnel_engine.db import (
    DEFAULT_DB_PATH,
    clear_emergency_brake,
    get_all_latest_snapshots,
    get_emergency_brakes,
    get_scheduler_heartbeat,
    get_source_watermarks,
    init_db,
)

if TYPE_CHECKING:
    from pathlib import Path

router = APIRouter()

MASKED_VALUE = "********"
ENV_PATH = PROJECT_ROOT / ".env"
WRITABLE_CONFIG_KEYS = frozenset(
    {
        "APP_PACKAGE_NAME",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GOOGLE_PLAY_STORE_CREDENTIALS",
        "GA4_PROPERTY_ID",
        "ADMOB_ACCOUNT_ID",
        "REVENUECAT_API_KEY",
        "REVENUECAT_PROJECT_ID",
        "GCS_PLAY_CONSOLE_BUCKET",
        "GOOGLE_ADS_CONFIGURATION_FILE_PATH",
        "GOOGLE_ADS_CUSTOMER_ID",
        "APP_STORE_CONNECT_KEY_ID",
        "APP_STORE_CONNECT_ISSUER_ID",
        "APP_STORE_CONNECT_PRIVATE_KEY",
        "APP_STORE_CONNECT_TEAM_ID",
        "JIRA_URL",
        "JIRA_USERNAME",
        "JIRA_API_TOKEN",
        "CONFLUENCE_URL",
        "CONFLUENCE_USERNAME",
        "GEMINI_API_KEY",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
    }
)
SENSITIVE_CONFIG_KEYS = frozenset(
    {
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GOOGLE_PLAY_STORE_CREDENTIALS",
        "GOOGLE_ADS_CONFIGURATION_FILE_PATH",
        "APP_STORE_CONNECT_PRIVATE_KEY",
        "REVENUECAT_API_KEY",
        "JIRA_API_TOKEN",
        "GEMINI_API_KEY",
        "TELEGRAM_BOT_TOKEN",
    }
)


class ConfigUpdateRequest(BaseModel):
    configs: dict[str, str]


def _age_seconds(timestamp: str | None) -> float | None:
    if not timestamp:
        return None
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return max(0.0, (datetime.now(UTC) - parsed).total_seconds())
    except ValueError:
        return None


def _source_state(watermark: dict[str, object], stale_after_hours: int = 36) -> str:
    status = str(watermark.get("last_status") or "unavailable")
    timestamp = watermark.get("last_completed_at") or watermark.get("last_started_at")
    age = _age_seconds(str(timestamp) if timestamp else None)
    if status == "failure":
        return "unavailable"
    if age is None:
        return "unavailable"
    if age > stale_after_hours * 3600:
        return "stale"
    return status


def _read_env_config(env_path: Path | None = None) -> dict[str, str]:
    env_path = env_path or ENV_PATH
    if not env_path.exists():
        return {}
    configs: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            key = key.strip()
            if key in WRITABLE_CONFIG_KEYS:
                configs[key] = value.strip()
    return configs


@router.get("/status")
def get_system_status() -> dict[str, object]:
    """Return persisted scheduler and connector health based on observed operations."""
    init_db(DEFAULT_DB_PATH)
    watermarks = get_source_watermarks(DEFAULT_DB_PATH)
    source_runs = []
    for watermark in watermarks:
        source_runs.append(
            {
                "source": watermark["source"],
                "package_name": watermark["package_name"] or None,
                "state": _source_state(watermark),
                "last_status": watermark["last_status"],
                "started_at": watermark["last_started_at"],
                "completed_at": watermark["last_completed_at"],
                "last_success_at": watermark["last_success_at"],
                "covered_period": {
                    "start": watermark["period_start"],
                    "end": watermark["period_end"],
                },
                "record_count": watermark["record_count"],
                "error": watermark["error_safe"],
            }
        )

    source_to_service = {
        "analytics": "analytics",
        "analytics_revenue": "analytics",
        "storefront": "play_store",
        "storefront_backfill": "play_store",
        "revenuecat": "revenuecat",
        "admob": "admob",
        "google_ads": "google_ads",
        "gcs_revenue": "gcs",
        "funnel": "funnel_engine",
    }
    services = dict.fromkeys(
        (
            "analytics",
            "play_store",
            "revenuecat",
            "admob",
            "aso",
            "google_ads",
            "gcs",
            "funnel_engine",
            "fcm_push",
            "journey_map",
        ),
        "unavailable",
    )
    latest_service_runs: dict[str, dict[str, object]] = {}
    for run in source_runs:
        service = source_to_service.get(str(run["source"]))
        if not service:
            continue
        current = latest_service_runs.get(service)
        run_timestamp = str(run["started_at"] or "")
        current_timestamp = str(current["started_at"] or "") if current else ""
        if current is None or run_timestamp > current_timestamp:
            latest_service_runs[service] = run
    for service, run in latest_service_runs.items():
        services[service] = str(run["state"])

    heartbeat = get_scheduler_heartbeat(DEFAULT_DB_PATH)
    heartbeat_age = _age_seconds(heartbeat.get("heartbeat_at") if heartbeat else None)
    scheduler_state = "unavailable"
    if heartbeat_age is not None:
        scheduler_state = "running" if heartbeat_age <= 300 else "stale"
    scheduler = {
        "state": scheduler_state,
        "heartbeat_at": heartbeat.get("heartbeat_at") if heartbeat else None,
        "process_started_at": heartbeat.get("process_started_at") if heartbeat else None,
        "last_cycle_started_at": heartbeat.get("last_cycle_started_at") if heartbeat else None,
        "last_cycle_completed_at": heartbeat.get("last_cycle_completed_at") if heartbeat else None,
        "last_cycle_status": heartbeat.get("last_cycle_status") if heartbeat else None,
        "error": heartbeat.get("last_error_safe") if heartbeat else None,
    }

    snapshots = get_all_latest_snapshots(DEFAULT_DB_PATH)
    latest = max(snapshots, key=lambda item: item.get("created_at") or "", default=None)
    latest_snapshot = None
    if latest:
        captured_at = latest.get("data_as_of") or latest.get("created_at")
        age = _age_seconds(captured_at)
        latest_snapshot = {
            "package_name": latest["package_name"],
            "snapshot_date": latest["snapshot_date"],
            "captured_at": captured_at,
            "state": "stale" if age is None or age > 36 * 3600 else "available",
            "partial": bool(latest.get("is_partial")),
        }
    return {
        "status": "ok",
        "trust_tier": get_latest_system_trust(),
        "last_prao_cycle": scheduler["last_cycle_completed_at"],
        "services": services,
        "scheduler": scheduler,
        "latest_snapshot": latest_snapshot,
        "source_runs": source_runs,
        "capabilities": {
            "read_only": env_enabled("MCP_GC_READ_ONLY"),
            "config_writes": config_writes_enabled(),
        },
    }


@router.get("/safety")
def get_system_safety() -> dict[str, object]:
    """Return persisted emergency-brake state."""
    active_brakes = get_emergency_brakes(DEFAULT_DB_PATH, active_only=True)
    return {
        "crash_rate": None,
        "crash_threshold": 1.0,
        "anr_rate": None,
        "anr_threshold": 0.47,
        "emergency_brake": "Triggered" if active_brakes else "Armed",
        "active_alerts": len(active_brakes),
        "affected_apps": [row["app_package"] for row in active_brakes],
    }


@router.delete("/safety/{package}/brake")
def reset_emergency_brake(package: str) -> dict[str, object]:
    """Explicitly re-arm writes for an app after operator review."""
    return {"success": clear_emergency_brake(DEFAULT_DB_PATH, package)}


@router.get("/config")
def get_system_config() -> dict[str, dict[str, str]]:
    """Return allowlisted configuration with secrets and file paths masked."""
    configs = _read_env_config()
    return {
        "configs": {
            key: MASKED_VALUE if key in SENSITIVE_CONFIG_KEYS and value else value
            for key, value in configs.items()
        }
    }


@router.post("/config")
def update_system_config(data: ConfigUpdateRequest) -> dict[str, object]:
    """Update allowlisted local configuration without replacing masked values."""
    if not config_writes_enabled():
        raise HTTPException(status_code=403, detail="Configuration writes are disabled")
    unknown = sorted(set(data.configs) - WRITABLE_CONFIG_KEYS)
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unsupported configuration keys: {unknown}")

    updates = {key: value for key, value in data.configs.items() if value != MASKED_VALUE}
    if any("\n" in value or "\r" in value for value in updates.values()):
        raise HTTPException(status_code=422, detail="Configuration values cannot contain newlines")

    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    remaining = dict(updates)
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in remaining:
            lines[index] = f"{key}={remaining.pop(key)}"
    lines.extend(f"{key}={value}" for key, value in remaining.items())
    ENV_PATH.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    for key, value in updates.items():
        if value:
            os.environ[key] = value
        else:
            os.environ.pop(key, None)
    return {"success": True, "updated_keys": sorted(updates)}
