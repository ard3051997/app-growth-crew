"""Per-app credential store.

Resolves credentials for a given package_name by:
1. Looking up the app entry in config/apps.json
2. Falling back to os.environ for any null/missing fields

This allows each app in the portfolio to have its own RevenueCat API key,
GA4 property, AdMob account, and Google Cloud service account — while
apps that share credentials simply leave those fields null.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import structlog

logger = structlog.get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
APPS_CONFIG_PATH = PROJECT_ROOT / "config" / "apps.json"


@dataclass
class AppCredentials:
    """Resolved credentials for a single app."""

    package_name: str

    # Google Cloud
    google_credentials_path: str | None = None

    # Google Analytics 4
    ga4_property_id: str | None = None

    # RevenueCat
    revenuecat_api_key: str | None = None
    revenuecat_project_id: str | None = None
    # "app_store" | "play_store" | None (None = cross-platform totals)
    rc_platform: str | None = None

    # AdMob
    admob_account_id: str | None = None

    # Google Cloud Storage
    gcs_play_console_bucket: str | None = None

    # Google Ads
    google_ads_config_path: str | None = None
    google_ads_customer_id: str | None = None

    # App Store Connect API
    app_store_connect_key_id: str | None = None
    app_store_connect_issuer_id: str | None = None
    app_store_connect_private_key_path: str | None = None
    team_id: str | None = None
    # Named `asc` CLI auth profile (see `asc doctor`) used for real ASC writes
    asc_profile: str | None = None

    # Atlassian (Jira/Confluence)
    jira_url: str | None = None
    jira_username: str | None = None
    jira_api_token: str | None = None
    confluence_url: str | None = None
    confluence_username: str | None = None

    # Journey Map
    events_md_path: str | None = None

    # Antigravity SDK
    gemini_api_key: str | None = None

    def has_revenuecat(self) -> bool:
        """Check if RevenueCat credentials are available."""
        return bool(self.revenuecat_api_key)

    def has_analytics(self) -> bool:
        """Check if GA4 credentials are available."""
        return bool(self.ga4_property_id and self.google_credentials_path)

    def has_admob(self) -> bool:
        """Check if AdMob credentials are available."""
        return bool(self.admob_account_id and self.google_credentials_path)

    def has_play_store(self) -> bool:
        """Check if Play Store credentials are available."""
        return bool(self.google_credentials_path)

    def has_atlassian(self) -> bool:
        """Check if Atlassian credentials are available."""
        return bool(self.jira_url and self.jira_username and self.jira_api_token)

    def has_google_ads(self) -> bool:
        """Check if Google Ads config is available."""
        return bool(self.google_ads_config_path and Path(self.google_ads_config_path).exists())

    def has_app_store_connect(self) -> bool:
        """Check if App Store Connect API credentials are available."""
        return bool(
            self.app_store_connect_key_id
            and self.app_store_connect_issuer_id
            and self.app_store_connect_private_key_path
        )

    def get_available_services(self) -> list[str]:
        """Return a list of services that have valid credentials."""
        services: list[str] = []
        if self.has_play_store():
            services.append("play_store")
        if self.has_revenuecat():
            services.append("revenuecat")
        if self.has_analytics():
            services.append("analytics")
        if self.has_admob():
            services.append("admob")
        if self.gcs_play_console_bucket and self.google_credentials_path:
            services.append("gcs")
        if self.has_atlassian():
            services.append("atlassian")
        if self.has_google_ads():
            services.append("google_ads")
        if self.has_app_store_connect():
            services.append("app_store_connect")
        # ASO is always available (uses public scraping)
        services.append("aso_keywords")
        return services


def _load_apps_config() -> list[dict[str, Any]]:
    """Load the apps.json config file."""
    if not APPS_CONFIG_PATH.exists():
        logger.warning("apps.json not found", path=str(APPS_CONFIG_PATH))
        return []
    try:
        with APPS_CONFIG_PATH.open() as f:
            data = json.load(f)
            if not isinstance(data, dict) or not isinstance(data.get("apps"), list):
                logger.error("apps.json must contain an apps array")
                return []
            return cast("list[dict[str, Any]]", data["apps"])
    except Exception as e:
        logger.exception("Failed to load apps.json", error=str(e))
        return []


def _find_app_entry(package_name: str) -> dict[str, Any] | None:
    """Find the app entry in apps.json by package_name."""
    apps = _load_apps_config()
    for app in apps:
        if app.get("package_name") == package_name:
            return app
    return None


def get_app_credentials(package_name: str) -> AppCredentials:
    """Resolve credentials for a given package_name.

    Lookup order for each field:
    1. App-specific value from apps.json (if not null)
    2. Global environment variable (os.environ)

    Args:
        package_name: The app package name to resolve credentials for.

    Returns:
        AppCredentials with all fields resolved.
    """
    app_entry = _find_app_entry(package_name) or {}
    env_pkg = os.environ.get("APP_PACKAGE_NAME")
    is_target_app = package_name == env_pkg

    def _resolve(app_key: str, env_key: str) -> str | None:
        """Return app-specific value if set, else fall back to env var."""
        val = app_entry.get(app_key)
        if val is not None and val != "":
            return str(val)
        return os.environ.get(env_key)

    # For app-specific RevenueCat credentials, do not fall back to global env vars
    # unless this app matches the target APP_PACKAGE_NAME.
    rc_api_key = app_entry.get("revenuecat_api_key")
    if rc_api_key is None or rc_api_key == "":
        rc_api_key = os.environ.get("REVENUECAT_API_KEY") if is_target_app else None
    else:
        rc_api_key = str(rc_api_key)

    rc_proj_id = app_entry.get("revenuecat_project_id")
    if rc_proj_id is None or rc_proj_id == "":
        rc_proj_id = os.environ.get("REVENUECAT_PROJECT_ID") if is_target_app else None
    else:
        rc_proj_id = str(rc_proj_id)

    return AppCredentials(
        package_name=package_name,
        google_credentials_path=_resolve(
            "google_credentials_path", "GOOGLE_APPLICATION_CREDENTIALS"
        ),
        ga4_property_id=_resolve("ga4_property_id", "GA4_PROPERTY_ID"),
        revenuecat_api_key=rc_api_key,
        revenuecat_project_id=rc_proj_id,
        admob_account_id=_resolve("admob_account_id", "ADMOB_ACCOUNT_ID"),
        gcs_play_console_bucket=_resolve("gcs_play_console_bucket", "GCS_PLAY_CONSOLE_BUCKET"),
        google_ads_config_path=_resolve(
            "google_ads_config_path", "GOOGLE_ADS_CONFIGURATION_FILE_PATH"
        ),
        google_ads_customer_id=_resolve("google_ads_customer_id", "GOOGLE_ADS_CUSTOMER_ID"),
        rc_platform=_resolve("rc_platform", "RC_PLATFORM"),
        app_store_connect_key_id=_resolve("app_store_connect_key_id", "APP_STORE_CONNECT_KEY_ID"),
        app_store_connect_issuer_id=_resolve(
            "app_store_connect_issuer_id", "APP_STORE_CONNECT_ISSUER_ID"
        ),
        app_store_connect_private_key_path=_resolve(
            "app_store_connect_private_key_path", "APP_STORE_CONNECT_PRIVATE_KEY"
        ),
        team_id=_resolve("team_id", "APP_STORE_CONNECT_TEAM_ID"),
        asc_profile=_resolve("asc_profile", "ASC_PROFILE"),
        jira_url=_resolve("jira_url", "JIRA_URL"),
        jira_username=_resolve("jira_username", "JIRA_USERNAME"),
        jira_api_token=_resolve("jira_api_token", "JIRA_API_TOKEN"),
        confluence_url=_resolve("confluence_url", "CONFLUENCE_URL"),
        confluence_username=_resolve("confluence_username", "CONFLUENCE_USERNAME"),
        events_md_path=_resolve("events_md_path", "EVENTS_MD_PATH"),
        gemini_api_key=os.environ.get("GEMINI_API_KEY"),
    )


def get_all_app_credentials() -> list[AppCredentials]:
    """Load credentials for all apps in the portfolio.

    Returns:
        List of AppCredentials, one per app in apps.json.
    """
    apps = _load_apps_config()
    return [get_app_credentials(app["package_name"]) for app in apps if app.get("package_name")]
