"""Tests for the app-specific credential store resolver."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from app_manager.credential_store import (
    AppCredentials,
    get_all_app_credentials,
    get_app_credentials,
)


def test_app_credentials_has_methods() -> None:
    # Test AppCredentials helper methods
    creds = AppCredentials(
        package_name="com.test.app",
        google_credentials_path="/path/to/creds.json",
        ga4_property_id="123456",
        revenuecat_api_key="rc_key_123",
        admob_account_id="pub-123",
        gcs_play_console_bucket="bucket_123",
    )
    assert creds.has_play_store() is True
    assert creds.has_analytics() is True
    assert creds.has_revenuecat() is True
    assert creds.has_admob() is True
    assert "play_store" in creds.get_available_services()
    assert "revenuecat" in creds.get_available_services()
    assert "analytics" in creds.get_available_services()
    assert "admob" in creds.get_available_services()
    assert "gcs" in creds.get_available_services()


@patch("app_manager.credential_store._load_apps_config")
def test_get_app_credentials_resolved_from_config(mock_load: MagicMock) -> None:
    # Set up config mockup
    mock_load.return_value = [
        {
            "package_name": "com.test.app",
            "ga4_property_id": "999888",
            "revenuecat_api_key": "app_specific_rc_key",
            "google_credentials_path": "/app/credentials.json",
        }
    ]

    with patch.dict(
        os.environ,
        {
            "GA4_PROPERTY_ID": "env_property_id",
            "REVENUECAT_API_KEY": "env_rc_key",
            "GOOGLE_APPLICATION_CREDENTIALS": "env_google_creds",
        },
    ):
        creds = get_app_credentials("com.test.app")
        # App-specific should override env vars
        assert creds.ga4_property_id == "999888"
        assert creds.revenuecat_api_key == "app_specific_rc_key"
        assert creds.google_credentials_path == "/app/credentials.json"


@patch("app_manager.credential_store._load_apps_config")
def test_get_app_credentials_falls_back_to_env(mock_load: MagicMock) -> None:
    # Set up config mockup with null/missing fields
    mock_load.return_value = [
        {
            "package_name": "com.test.app",
            "ga4_property_id": None,
            "revenuecat_api_key": "",
        }
    ]

    with patch.dict(
        os.environ,
        {
            "APP_PACKAGE_NAME": "com.test.app",
            "GA4_PROPERTY_ID": "env_property_id",
            "REVENUECAT_API_KEY": "env_rc_key",
            "GOOGLE_APPLICATION_CREDENTIALS": "/env/google/creds.json",
        },
    ):
        creds = get_app_credentials("com.test.app")
        # Null/empty config fields should fall back to env vars
        assert creds.ga4_property_id == "env_property_id"
        assert creds.revenuecat_api_key == "env_rc_key"
        assert creds.google_credentials_path == "/env/google/creds.json"


@patch("app_manager.credential_store._load_apps_config")
def test_get_all_app_credentials(mock_load: MagicMock) -> None:
    mock_load.return_value = [
        {"package_name": "com.app.one", "ga4_property_id": "1"},
        {"package_name": "com.app.two", "ga4_property_id": "2"},
    ]
    all_creds = get_all_app_credentials()
    assert len(all_creds) == 2
    assert all_creds[0].package_name == "com.app.one"
    assert all_creds[1].package_name == "com.app.two"
