"""Platform dispatch for store listing reads/writes.

ExperimentLifecycle, the shadow study, and the store-conversion-proposal endpoint
all need to read and write an app's store listing without caring whether the app
is on Google Play or the Apple App Store. This module is the single place that
decides which platform client to use for a given package, based on
credential_store.get_app_credentials(package).rc_platform — so Play Store stays
the default for every app that hasn't explicitly set rc_platform to "app_store".
"""

from __future__ import annotations

from typing import Any

from app_manager.credential_store import get_app_credentials
from app_store_mcp.client import AppStoreClient
from play_store_mcp.client import PlayStoreClient

DEFAULT_LOCALE = "en-US"


def is_app_store(package: str) -> bool:
    """Return True if this package is configured as an Apple App Store app."""
    return get_app_credentials(package).rc_platform == "app_store"


def read_listing(package: str, language: str = DEFAULT_LOCALE) -> dict[str, Any]:
    """Read the current live/draft listing for an app, regardless of platform.

    Returns the canonical {packageName, language, title, short_description,
    full_description} shape shared by both platforms.
    """
    credentials = get_app_credentials(package)
    if credentials.rc_platform == "app_store":
        client = AppStoreClient()
        return client.get_asc_listing(package, locale=language, profile=credentials.asc_profile)

    client = PlayStoreClient(credentials_path=credentials.google_credentials_path)
    listing = client.get_listing(package_name=package, language=language)
    return {
        "packageName": package,
        "language": listing.language,
        "title": listing.title,
        "short_description": listing.short_description,
        "full_description": listing.full_description,
        "video": listing.video,
    }


def write_listing(package: str, args: dict[str, Any]) -> dict[str, Any]:
    """Write a listing update for an app, regardless of platform.

    Returns a dict with a `success` key so callers (ExperimentLifecycle's
    write-verification) work the same way no matter which platform client
    actually performed the write.
    """
    credentials = get_app_credentials(package)
    language = args.get("language") or DEFAULT_LOCALE

    if credentials.rc_platform == "app_store":
        client = AppStoreClient()
        return client.update_listing(
            package,
            title=args.get("title"),
            short_description=args.get("shortDescription"),
            full_description=args.get("fullDescription"),
            locale=language,
            profile=credentials.asc_profile,
        )

    client = PlayStoreClient(credentials_path=credentials.google_credentials_path)
    result = client.update_listing(
        package_name=package,
        language=language,
        title=args.get("title"),
        short_description=args.get("shortDescription"),
        full_description=args.get("fullDescription"),
        video=args.get("video"),
    )
    return result.model_dump()
