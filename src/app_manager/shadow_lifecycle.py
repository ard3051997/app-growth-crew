"""A fake store listing state for running the real ExperimentLifecycle safely.

ExperimentLifecycle already accepts injectable listing_reader/listing_writer
callables and an arbitrary db_path (see ExperimentLifecycle.__init__). This module
uses that seam, unmodified, to run the exact production auto_low_risk pipeline
(validate -> approve -> execute -> read-after-write verify) against an app's real
listing text and real funnel evidence, without ever calling a real store write
API (Play Store or App Store Connect). Only the final write is faked; everything
upstream (reading the current listing once for realism, reading country
performance, generating ASO copy) is a real, read-only call.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app_manager import store_listing_client
from app_manager.experiment_lifecycle import ExperimentLifecycle
from funnel_engine.db import init_db

if TYPE_CHECKING:
    from pathlib import Path

EXECUTABLE_LOCALE = "en-US"


def _normalize(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return dict(value.model_dump())
    if isinstance(value, dict):
        return dict(value)
    return {}


class ShadowListingStore:
    """In-memory store listing state, seeded once from a real read-only fetch.

    Mirrors the (package, language) -> listing shape ExperimentLifecycle expects
    from its listing_reader/listing_writer, but every write after the initial seed
    stays local to this object. No call after construction ever reaches a real
    write API, regardless of whether the app is on Play Store or App Store Connect.
    """

    def __init__(self) -> None:
        self._state: dict[tuple[str, str], dict[str, Any]] = {}

    @staticmethod
    def _seed(package: str, language: str) -> dict[str, Any]:
        return _normalize(store_listing_client.read_listing(package, language))

    def read(self, package: str, language: str) -> dict[str, Any]:
        key = (package, language)
        if key not in self._state:
            seeded = self._seed(package, language)
            self._state[key] = {
                "packageName": package,
                "language": language,
                "title": seeded.get("title"),
                "short_description": seeded.get("short_description"),
                "full_description": seeded.get("full_description"),
                "video": seeded.get("video"),
            }
        return dict(self._state[key])

    def write(self, package: str, args: dict[str, Any]) -> dict[str, Any]:
        language = args.get("language", EXECUTABLE_LOCALE)
        key = (package, language)
        current = dict(self._state.get(key) or {"packageName": package, "language": language})
        if args.get("title") is not None:
            current["title"] = args["title"]
        if args.get("shortDescription") is not None:
            current["short_description"] = args["shortDescription"]
        if args.get("fullDescription") is not None:
            current["full_description"] = args["fullDescription"]
        current["packageName"] = package
        current["language"] = language
        self._state[key] = current
        result = dict(current)
        result["success"] = True
        return result


def build_shadow_lifecycle(
    db_path: str | Path, *, rulebook_dir: str | Path | None = None
) -> ExperimentLifecycle:
    """Construct a real ExperimentLifecycle backed by a throwaway DB and a fake writer."""
    init_db(db_path)
    store = ShadowListingStore()
    return ExperimentLifecycle(
        db_path,
        rulebook_dir=rulebook_dir,
        listing_reader=store.read,
        listing_writer=store.write,
    )
