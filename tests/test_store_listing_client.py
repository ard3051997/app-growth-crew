"""Tests for platform dispatch between Play Store and App Store Connect."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app_manager import store_listing_client
from app_manager.credential_store import AppCredentials
from app_store_mcp.client import AppStoreClient
from play_store_mcp.client import PlayStoreClient
from play_store_mcp.models import Listing, ListingUpdateResult

PACKAGE = "com.example.app"


def _play_credentials() -> AppCredentials:
    return AppCredentials(package_name=PACKAGE, google_credentials_path="creds.json")


def _app_store_credentials() -> AppCredentials:
    return AppCredentials(package_name=PACKAGE, rc_platform="app_store", asc_profile="LightRayKey")


class TestIsAppStore:
    def test_true_when_rc_platform_is_app_store(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            store_listing_client, "get_app_credentials", lambda _pkg: _app_store_credentials()
        )
        assert store_listing_client.is_app_store(PACKAGE) is True

    def test_false_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            store_listing_client, "get_app_credentials", lambda _pkg: _play_credentials()
        )
        assert store_listing_client.is_app_store(PACKAGE) is False


class TestReadListing:
    def test_reads_via_play_store_client_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            store_listing_client, "get_app_credentials", lambda _pkg: _play_credentials()
        )
        mock_client = MagicMock(spec=PlayStoreClient)
        mock_client.get_listing.return_value = Listing(
            language="en-US", title="T", short_description="S", full_description="F"
        )
        monkeypatch.setattr(store_listing_client, "PlayStoreClient", lambda **_kw: mock_client)

        result = store_listing_client.read_listing(PACKAGE, "en-US")

        mock_client.get_listing.assert_called_once_with(package_name=PACKAGE, language="en-US")
        assert result == {
            "packageName": PACKAGE,
            "language": "en-US",
            "title": "T",
            "short_description": "S",
            "full_description": "F",
            "video": None,
        }

    def test_reads_via_app_store_client_when_rc_platform_is_app_store(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            store_listing_client, "get_app_credentials", lambda _pkg: _app_store_credentials()
        )
        mock_client = MagicMock(spec=AppStoreClient)
        mock_client.get_asc_listing.return_value = {
            "packageName": PACKAGE,
            "language": "en-GB",
            "title": "Pomodori",
            "short_description": "Focus Timer",
            "full_description": "Long description",
        }
        monkeypatch.setattr(store_listing_client, "AppStoreClient", lambda: mock_client)

        result = store_listing_client.read_listing(PACKAGE, "en-GB")

        mock_client.get_asc_listing.assert_called_once_with(
            PACKAGE, locale="en-GB", profile="LightRayKey"
        )
        assert result["title"] == "Pomodori"


class TestWriteListing:
    def test_writes_via_play_store_client_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            store_listing_client, "get_app_credentials", lambda _pkg: _play_credentials()
        )
        mock_client = MagicMock(spec=PlayStoreClient)
        mock_client.update_listing.return_value = ListingUpdateResult(
            success=True, package_name=PACKAGE, language="en-US", message="ok"
        )
        monkeypatch.setattr(store_listing_client, "PlayStoreClient", lambda **_kw: mock_client)

        result = store_listing_client.write_listing(
            PACKAGE, {"language": "en-US", "title": "New Title"}
        )

        mock_client.update_listing.assert_called_once_with(
            package_name=PACKAGE,
            language="en-US",
            title="New Title",
            short_description=None,
            full_description=None,
            video=None,
        )
        assert result["success"] is True

    def test_writes_via_app_store_client_when_rc_platform_is_app_store(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            store_listing_client, "get_app_credentials", lambda _pkg: _app_store_credentials()
        )
        mock_client = MagicMock(spec=AppStoreClient)
        mock_client.update_listing.return_value = {"status": "success", "success": True}
        monkeypatch.setattr(store_listing_client, "AppStoreClient", lambda: mock_client)

        result = store_listing_client.write_listing(
            PACKAGE,
            {"language": "en-GB", "title": "New Title", "shortDescription": "New subtitle"},
        )

        mock_client.update_listing.assert_called_once_with(
            PACKAGE,
            title="New Title",
            short_description="New subtitle",
            full_description=None,
            locale="en-GB",
            profile="LightRayKey",
        )
        assert result["success"] is True

    def test_defaults_missing_language_to_en_us(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            store_listing_client, "get_app_credentials", lambda _pkg: _app_store_credentials()
        )
        mock_client = MagicMock(spec=AppStoreClient)
        mock_client.update_listing.return_value = {"success": True}
        monkeypatch.setattr(store_listing_client, "AppStoreClient", lambda: mock_client)

        store_listing_client.write_listing(PACKAGE, {"title": "New Title"})

        assert mock_client.update_listing.call_args.kwargs["locale"] == "en-US"
