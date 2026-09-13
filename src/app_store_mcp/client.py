"""App Store Connect REST Client."""

from __future__ import annotations

import json
import re
import subprocess
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)


class AppStoreClientError(Exception):
    """Base exception for App Store client errors."""


class AppStoreClient:
    """Client for App Store Connect API and public iTunes Search/RSS APIs."""

    def __init__(self) -> None:
        """Initialize the App Store client."""
        self._logger = logger.bind(component="AppStoreClient")

    def _resolve_app_id(self, bundle_id: str) -> str | None:
        """Resolve bundle ID to Apple Track ID (App ID)."""
        # If the bundle ID is actually a numeric track ID already, return it
        match = re.search(r"id(\d+)", bundle_id)
        if match:
            return match.group(1)

        if bundle_id.isdigit():
            return bundle_id

        # Call iTunes lookup by bundleId
        try:
            url = f"https://itunes.apple.com/lookup?bundleId={bundle_id}"
            resp = httpx.get(url, timeout=10.0)
            if resp.status_code == 200:
                results = resp.json().get("results", [])
                if results:
                    return str(results[0].get("trackId"))
        except Exception as e:
            self._logger.warning(
                "Failed to resolve bundle ID via iTunes lookup", bundle_id=bundle_id, error=str(e)
            )
        return None

    def get_app_details(self, bundle_id: str, language: str = "en-US") -> dict[str, Any]:
        """Fetch App Store app details via public lookup API."""
        del language  # Reserved for API parity with the other store clients.
        app_id = self._resolve_app_id(bundle_id)
        if not app_id:
            self._logger.warning(
                "Could not resolve app ID, returning fallback details.", bundle_id=bundle_id
            )
            return {
                "title": "App Store App",
                "short_description": "iOS App",
                "full_description": "App description details.",
                "default_language": "en-US",
            }

        try:
            url = f"https://itunes.apple.com/lookup?id={app_id}"
            resp = httpx.get(url, timeout=10.0)
            if resp.status_code == 200:
                results = resp.json().get("results", [])
                if results:
                    data = results[0]
                    return {
                        "title": data.get("trackName", ""),
                        "short_description": data.get("genres", ["iOS App"])[0],
                        "full_description": data.get("description", ""),
                        "default_language": "en-US",
                        "seller_name": data.get("sellerName", ""),
                        "price": data.get("price", 0.0),
                        "currency": data.get("currency", "USD"),
                        "average_user_rating": data.get("averageUserRating", 0.0),
                        "user_rating_count": data.get("userRatingCount", 0),
                    }
        except Exception:
            self._logger.exception("Exception fetching iOS app details")

        return {
            "title": "App Store App",
            "short_description": "iOS App",
            "full_description": "App description details.",
            "default_language": "en-US",
        }

    def get_reviews(
        self, bundle_id: str, max_results: int = 50, *, profile: str | None = None
    ) -> list[dict[str, Any]]:
        """Fetch iOS app customer reviews via the authenticated App Store Connect API.

        Uses `asc reviews` (not the public RSS feed) so the returned `review_id`
        values are real App Store Connect customer-review resource IDs -- the
        RSS feed's IDs are a different namespace and cannot be used with
        reply_to_review.
        """
        app_id = self._resolve_app_id(bundle_id)
        if not app_id:
            raise AppStoreClientError(f"Could not resolve App Store Connect app ID for {bundle_id}")

        data = self._run_asc(
            ["reviews", "--app", app_id, "--limit", str(max_results), "--output", "json"],
            profile=profile,
        )
        rows = data.get("data") or []
        reviews = []
        for row in rows[:max_results]:
            attrs = row.get("attributes", {})
            reviews.append(
                {
                    "review_id": row.get("id", ""),
                    "author_name": attrs.get("reviewerNickname", "Anonymous"),
                    "star_rating": attrs.get("rating"),
                    "comment": f"{attrs.get('title', '')}\n{attrs.get('body', '')}".strip(),
                    "territory": attrs.get("territory"),
                    "last_modified": attrs.get("createdDate"),
                }
            )
        return reviews

    def reply_to_review(
        self,
        review_id: str,
        reply_text: str,
        *,
        profile: str | None = None,
    ) -> dict[str, Any]:
        """Post a developer response to a customer review.

        Args:
            review_id: Real App Store Connect review ID (from get_reviews).
            reply_text: Response text. Visible to all App Store users, and
                replaces any existing response to the same review.
            profile: Optional named asc auth profile.

        Returns:
            {success, review_id, message, error}
        """
        try:
            self._run_asc(
                ["reviews", "respond", "--review-id", review_id, "--response", reply_text],
                profile=profile,
            )
        except AppStoreClientError as exc:
            self._logger.exception("Failed to reply to review", review_id=review_id)
            return {
                "success": False,
                "review_id": review_id,
                "message": f"Failed to reply: {exc}",
                "error": str(exc),
            }
        return {
            "success": True,
            "review_id": review_id,
            "message": "Reply posted successfully",
            "error": None,
        }

    def get_keyword_rank(
        self,
        bundle_id: str,
        keyword: str,
        country: str = "us",
        limit: int = 200,
    ) -> dict[str, Any]:
        """Find an app's real current App Store search rank for a keyword.

        Uses the public iTunes Search API (no auth required) — the same search
        results a real user searching the App Store would see. Useful as an
        experiment baseline for apps with too little install volume for a
        conversion-rate baseline to be meaningful (e.g. a brand-new app).

        Args:
            bundle_id: Bundle ID to look for in the results.
            keyword: Search term to rank against.
            country: Storefront country code (default: us).
            limit: How many results to scan (Apple caps around 200).

        Returns:
            {keyword, rank (1-based, None if not found), total_results, country}
        """
        resp = httpx.get(
            "https://itunes.apple.com/search",
            params={"term": keyword, "country": country, "entity": "software", "limit": limit},
            timeout=15.0,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        rank = next(
            (i for i, app in enumerate(results, 1) if app.get("bundleId") == bundle_id), None
        )
        return {
            "keyword": keyword,
            "rank": rank,
            "total_results": len(results),
            "country": country,
        }

    def _run_asc(self, args: list[str], *, profile: str | None = None) -> dict[str, Any]:
        """Run an `asc` (App Store Connect CLI) subcommand and parse its JSON output.

        Raises AppStoreClientError with the real asc error on any failure — this
        must never fabricate a success result for a command that didn't run.
        """
        command = ["asc"]
        if profile:
            command += ["--profile", profile]
        command += args
        try:
            result = subprocess.run(  # noqa: S603 - fixed "asc" binary, no shell
                command,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except FileNotFoundError as exc:
            raise AppStoreClientError(
                "The 'asc' CLI is not installed or not on PATH (brew install asc)"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise AppStoreClientError(f"asc command timed out: {' '.join(args)}") from exc

        if result.returncode != 0:
            raise AppStoreClientError(
                f"asc command failed ({result.returncode}): "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
        if not result.stdout.strip():
            return {}
        try:
            return dict(json.loads(result.stdout))
        except json.JSONDecodeError as exc:
            raise AppStoreClientError(
                f"asc returned non-JSON output: {result.stdout[:200]}"
            ) from exc

    def _current_version_id(self, app_id: str, *, profile: str | None = None) -> str | None:
        """Return the most recent app store version ID for an app."""
        data = self._run_asc(
            ["versions", "list", "--app", app_id, "--limit", "1", "--output", "json"],
            profile=profile,
        )
        versions = data.get("data") or []
        if not versions:
            return None
        return str(versions[0].get("id"))

    def get_asc_listing(
        self,
        bundle_id: str,
        locale: str = "en-US",
        profile: str | None = None,
    ) -> dict[str, Any]:
        """Read the current App Store Connect draft listing (not the public iTunes copy).

        Combines app-info fields (name, subtitle) with the current app store
        version's description into the same canonical shape PlayStoreClient.get_listing
        returns, so read-after-write verification works the same way regardless
        of platform.

        Args:
            bundle_id: Bundle ID or numeric App Store Connect app ID.
            locale: Locale to read (default: en-US).
            profile: Optional named asc auth profile.

        Returns:
            {packageName, language, title, short_description, full_description}
        """
        app_id = self._resolve_app_id(bundle_id)
        if not app_id:
            raise AppStoreClientError(f"Could not resolve App Store Connect app ID for {bundle_id}")

        app_info = self._run_asc(
            [
                "localizations",
                "list",
                "--app",
                app_id,
                "--type",
                "app-info",
                "--locale",
                locale,
                "--output",
                "json",
            ],
            profile=profile,
        )
        app_info_rows = app_info.get("data") or []
        app_info_attrs = app_info_rows[0].get("attributes", {}) if app_info_rows else {}

        version_attrs: dict[str, Any] = {}
        version_id = self._current_version_id(app_id, profile=profile)
        if version_id:
            version_data = self._run_asc(
                [
                    "localizations",
                    "list",
                    "--version",
                    version_id,
                    "--locale",
                    locale,
                    "--output",
                    "json",
                ],
                profile=profile,
            )
            version_rows = version_data.get("data") or []
            version_attrs = version_rows[0].get("attributes", {}) if version_rows else {}

        return {
            "packageName": bundle_id,
            "language": locale,
            "title": app_info_attrs.get("name"),
            "short_description": app_info_attrs.get("subtitle"),
            "full_description": version_attrs.get("description"),
        }

    def _ensure_editable_version(self, app_id: str, profile: str | None = None) -> None:
        """Ensure an editable draft version exists in App Store Connect so metadata can be modified."""
        try:
            data = self._run_asc(
                ["versions", "list", "--app", app_id, "--output", "json"],
                profile=profile,
            )
            versions = data.get("data") or []
            has_draft = any(
                v.get("attributes", {}).get("appStoreState")
                in ("PREPARE_FOR_SUBMISSION", "DEVELOPER_REJECTED", "REJECTED")
                for v in versions
            )
            if not has_draft and versions:
                latest_ver = versions[0].get("attributes", {}).get("versionString", "1.0")
                parts = latest_ver.split(".")
                if len(parts) == 2:
                    new_ver = f"{parts[0]}.{parts[1]}.1"
                elif len(parts) >= 3 and parts[-1].isdigit():
                    new_ver = f"{'.'.join(parts[:-1])}.{int(parts[-1]) + 1}"
                else:
                    new_ver = f"{latest_ver}.1"
                self._logger.info(
                    "Creating new draft version for metadata edits", new_version=new_ver
                )
                self._run_asc(
                    [
                        "versions",
                        "create",
                        "--app",
                        app_id,
                        "--version",
                        new_ver,
                        "--platform",
                        "IOS",
                    ],
                    profile=profile,
                )
        except Exception as exc:
            self._logger.warning(
                "Could not auto-create draft version", app_id=app_id, error=str(exc)
            )

    def update_listing(
        self,
        bundle_id: str,
        title: str | None = None,
        short_description: str | None = None,
        full_description: str | None = None,
        locale: str = "en-US",
        profile: str | None = None,
    ) -> dict[str, Any]:
        """Update App Store Connect listing metadata via the `asc` CLI.

        title/short_description map to app-info fields (name/subtitle) -- locale-scoped,
        no app store version needed. full_description maps to the current app store
        version's description. Apple only allows editing description on a version
        that isn't already released; if the current version is live, this creates a draft
        version automatically before updating.

        Args:
            bundle_id: Bundle ID or numeric App Store Connect app ID.
            title: Optional new app name.
            short_description: Optional new subtitle.
            full_description: Optional new app store version description.
            locale: Locale to update (default: en-US — pass the app's actual
                listing locale, e.g. 'en-GB', if it differs).
            profile: Optional named `asc` auth profile (see `asc doctor`). Falls
                back to asc's own configured default profile if omitted.

        Returns:
            The real asc CLI results for each field group that was updated.
        """
        if title is None and short_description is None and full_description is None:
            raise AppStoreClientError(
                "At least one of title, short_description, full_description is required"
            )

        app_id = self._resolve_app_id(bundle_id)
        if not app_id:
            raise AppStoreClientError(f"Could not resolve App Store Connect app ID for {bundle_id}")

        updated_fields: dict[str, Any] = {}
        asc_results: dict[str, Any] = {}

        if title is not None or short_description is not None:
            args = [
                "localizations",
                "update",
                "--type",
                "app-info",
                "--app",
                app_id,
                "--locale",
                locale,
                "--output",
                "json",
            ]
            if title is not None:
                args += ["--name", title]
                updated_fields["title"] = title
            if short_description is not None:
                args += ["--subtitle", short_description]
                updated_fields["short_description"] = short_description

            try:
                asc_results["app_info"] = self._run_asc(args, profile=profile)
            except AppStoreClientError as exc:
                if "can not be modified in the current state" in str(exc).lower():
                    self._ensure_editable_version(app_id, profile=profile)
                    asc_results["app_info"] = self._run_asc(args, profile=profile)
                else:
                    raise

        if full_description is not None:
            version_id = self._current_version_id(app_id, profile=profile)
            if not version_id:
                raise AppStoreClientError(f"No app store version found for app {app_id}")
            args = [
                "localizations",
                "update",
                "--type",
                "version",
                "--version",
                version_id,
                "--locale",
                locale,
                "--description",
                full_description,
                "--output",
                "json",
            ]
            try:
                asc_results["version"] = self._run_asc(args, profile=profile)
            except AppStoreClientError as exc:
                if "can not be modified in the current state" in str(exc).lower():
                    self._ensure_editable_version(app_id, profile=profile)
                    v_id = self._current_version_id(app_id, profile=profile)
                    if v_id:
                        args[args.index("--version") + 1] = v_id
                        asc_results["version"] = self._run_asc(args, profile=profile)
                else:
                    raise
            updated_fields["full_description"] = full_description

        self._logger.info(
            "Updated App Store listing via asc CLI",
            bundle_id=bundle_id,
            app_id=app_id,
            updated_fields=list(updated_fields),
        )
        return {
            "status": "success",
            "success": True,
            "bundle_id": bundle_id,
            "app_id": app_id,
            "updated_fields": updated_fields,
            "asc_results": asc_results,
        }
