"""Centralized configuration for the App Management System."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast


@dataclass
class AppManagerConfig:
    """Configuration for the App Management System.

    Credentials and IDs are loaded from environment variables by default.
    """

    # Target app
    package_name: str = ""

    # Google Play Store credentials
    google_credentials_path: str | None = None

    # RevenueCat credentials
    revenuecat_api_key: str | None = None
    revenuecat_project_id: str | None = None

    # Google Analytics 4
    ga4_property_id: str | None = None

    # AdMob
    admob_account_id: str | None = None

    # Google Cloud Storage
    gcs_play_console_bucket: str | None = None

    # Google Ads Configuration
    google_ads_config_path: str | None = None

    # Atlassian (Jira/Confluence)
    jira_url: str | None = None
    jira_username: str | None = None
    jira_api_token: str | None = None
    confluence_url: str | None = None
    confluence_username: str | None = None

    # Antigravity SDK
    gemini_api_key: str | None = None

    @classmethod
    def from_env(cls) -> AppManagerConfig:
        """Load configuration from environment variables.

        Environment variables:
            APP_PACKAGE_NAME: Target app package name
            GOOGLE_APPLICATION_CREDENTIALS: Path to Google service account JSON
            REVENUECAT_API_KEY: RevenueCat API secret key
            REVENUECAT_PROJECT_ID: RevenueCat project ID
            GA4_PROPERTY_ID: Google Analytics 4 property ID
            ADMOB_ACCOUNT_ID: AdMob publisher/account ID
            GOOGLE_ADS_CONFIGURATION_FILE_PATH: Path to Google Ads configuration YAML
            JIRA_URL: Jira instance URL
            JIRA_USERNAME: Jira username (email)
            JIRA_API_TOKEN: Jira API token
            CONFLUENCE_URL: Confluence instance URL
            CONFLUENCE_USERNAME: Confluence username (email)
            GEMINI_API_KEY: Gemini API key for Antigravity SDK

        Returns:
            Populated AppManagerConfig.
        """
        # Load from .env file if it exists in current directory and we are not in tests
        import sys

        dotenv_path = Path(".env")
        if dotenv_path.exists() and "pytest" not in sys.modules:
            try:
                with dotenv_path.open() as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            key, val = line.split("=", 1)
                            key = key.strip()
                            val = val.strip().strip("'\"")
                            # Only set if not already set in process environment to respect manual exports
                            if key and key not in os.environ:
                                os.environ[key] = val
            except OSError as exc:
                import warnings

                warnings.warn(f"Could not read .env file: {exc}", stacklevel=2)

        google_ads_path = os.environ.get("GOOGLE_ADS_CONFIGURATION_FILE_PATH")
        if not google_ads_path:
            default_path = Path.cwd() / "google-ads.yaml"
            if default_path.exists():
                google_ads_path = str(default_path)

        return cls(
            package_name=os.environ.get("APP_PACKAGE_NAME", ""),
            google_credentials_path=os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"),
            revenuecat_api_key=os.environ.get("REVENUECAT_API_KEY"),
            revenuecat_project_id=os.environ.get("REVENUECAT_PROJECT_ID"),
            ga4_property_id=os.environ.get("GA4_PROPERTY_ID"),
            admob_account_id=os.environ.get("ADMOB_ACCOUNT_ID"),
            gcs_play_console_bucket=os.environ.get("GCS_PLAY_CONSOLE_BUCKET"),
            google_ads_config_path=google_ads_path,
            jira_url=os.environ.get("JIRA_URL"),
            jira_username=os.environ.get("JIRA_USERNAME"),
            jira_api_token=os.environ.get("JIRA_API_TOKEN"),
            confluence_url=os.environ.get("CONFLUENCE_URL"),
            confluence_username=os.environ.get("CONFLUENCE_USERNAME"),
            gemini_api_key=os.environ.get("GEMINI_API_KEY"),
        )

    def get_available_services(self) -> list[str]:
        """Return a list of services that have credentials configured.

        Returns:
            List of service names with valid configuration.
        """
        services: list[str] = []

        if self.google_credentials_path:
            services.append("play_store")

        if self.revenuecat_api_key:
            services.append("revenuecat")

        if self.ga4_property_id:
            services.append("analytics")

        if self.admob_account_id:
            services.append("admob")

        if self.google_credentials_path and self.gcs_play_console_bucket:
            services.append("gcs")

        if self.google_ads_config_path and Path(self.google_ads_config_path).exists():
            services.append("google_ads")

        if self.jira_url and self.jira_username and self.jira_api_token:
            services.append("atlassian")

        # ASO always available (uses public scraping)
        services.append("aso_keywords")

        if self.gemini_api_key:
            services.append("image_gen")

        return services

    def validate(self) -> list[str]:
        """Validate configuration and return warnings.

        Returns:
            List of warning messages for missing or conflicting configurations.
        """
        msgs: list[str] = []

        if not self.gemini_api_key:
            msgs.append(
                "GEMINI_API_KEY not set — the coordinator cannot start. "
                "Get one at: https://aistudio.google.com/app/api-keys"
            )

        if not self.package_name:
            msgs.append("APP_PACKAGE_NAME not set. Some tools require a default package name.")

        if not self.google_credentials_path:
            msgs.append(
                "GOOGLE_APPLICATION_CREDENTIALS not set. Play Store, Analytics, AdMob, "
                "GCS, and Funnel Engine tools will not be available."
            )
        elif not Path(self.google_credentials_path).exists():
            msgs.append(
                f"GOOGLE_APPLICATION_CREDENTIALS file not found: {self.google_credentials_path}"
            )

        # Mutual dependency: GA4 without Google creds silently dies at runtime
        if self.ga4_property_id and not self.google_credentials_path:
            msgs.append(
                "GA4_PROPERTY_ID is set but GOOGLE_APPLICATION_CREDENTIALS is missing — "
                "Analytics tools will fail at runtime."
            )

        if self.admob_account_id and not self.google_credentials_path:
            msgs.append(
                "ADMOB_ACCOUNT_ID is set but GOOGLE_APPLICATION_CREDENTIALS is missing — "
                "AdMob tools will fail at runtime."
            )

        if not self.revenuecat_api_key:
            msgs.append(
                "REVENUECAT_API_KEY not set. Subscription revenue tools will not be available."
            )

        if not self.ga4_property_id:
            msgs.append("GA4_PROPERTY_ID not set. Analytics tools will not be available.")

        if not self.admob_account_id:
            msgs.append("ADMOB_ACCOUNT_ID not set. Ad revenue tools will not be available.")

        if not self.gcs_play_console_bucket:
            msgs.append(
                "GCS_PLAY_CONSOLE_BUCKET not set. Play Console GCS reports will not be available."
            )

        if not self.google_ads_config_path or not Path(self.google_ads_config_path).exists():
            msgs.append(
                "google-ads.yaml not found. Google Ads campaign tools will not be available."
            )

        return msgs

    def validate_or_exit(self) -> None:
        """Validate critical configuration and exit with a clear error if GEMINI_API_KEY is missing."""
        import sys

        msgs = self.validate()
        critical = [m for m in msgs if "GEMINI_API_KEY" in m or "not found:" in m]
        if critical:
            for m in critical:
                print(f"❌ {m}")
            sys.exit(1)

    def get_rulebook(self) -> dict[Any, Any] | None:
        """Load the app-specific rule book if it exists in the rulebooks directory."""
        if not self.package_name:
            return None

        rulebook_path = Path("rulebooks") / f"{self.package_name}.yaml"
        if not rulebook_path.exists():
            return None

        import yaml

        try:
            with rulebook_path.open() as f:
                return cast("dict[Any, Any] | None", yaml.safe_load(f))
        except Exception:
            return None
