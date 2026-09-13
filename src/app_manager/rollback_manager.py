"""Rollback Manager to capture pre-experiment state and handle automated reverts."""

from __future__ import annotations

from typing import Any, cast

import structlog

from app_manager.credential_store import get_app_credentials
from play_store_mcp.client import PlayStoreClient
from revenuecat_mcp.client import RevenueCatClient

logger = structlog.get_logger("rollback_manager")


class RollbackManager:
    """Manages snapshot capturing and rollbacks for mutating MCP operations."""

    async def capture_snapshot(
        self, experiment_type: str, app_package: str, args: dict[str, Any]
    ) -> dict[str, Any]:
        """Capture the current state of the resource before modifying it.

        Args:
            experiment_type: Type of the experiment (e.g. 'aso_metadata')
            app_package: The target app package name
            args: The arguments of the proposed change (used to locate which language/offering is being changed)
        """
        logger.info(
            "Capturing pre-experiment state snapshot", app=app_package, type=experiment_type
        )
        credentials = get_app_credentials(app_package)

        if experiment_type in ("aso_metadata", "play_store/update_listing"):
            language = args.get("language", args.get("languageCode", "en-US"))
            try:
                play_client = PlayStoreClient(credentials_path=credentials.google_credentials_path)
                listing = play_client.get_listing(package_name=app_package, language=language)
                return {
                    "language": language,
                    "title": listing.title,
                    "short_description": listing.short_description,
                    "full_description": listing.full_description,
                    "video": listing.video,
                }
            except Exception as e:
                logger.exception("Failed to capture listing snapshot", error=str(e))
                return {}

        elif experiment_type == "paywall_variant":
            offering_id = args.get("offering_id", "default")
            try:
                revenuecat_client = RevenueCatClient(
                    api_key=credentials.revenuecat_api_key,
                    project_id=credentials.revenuecat_project_id,
                )
                offering = revenuecat_client.get_offering(offering_id=offering_id)
                return cast("dict[str, Any]", offering.model_dump())
            except Exception as e:
                logger.exception("Failed to capture offering snapshot", error=str(e))
                return {}

        return {}

    async def execute_rollback(
        self, experiment_type: str, app_package: str, snapshot_before: dict[str, Any]
    ) -> bool:
        """Execute the rollback using the pre-experiment snapshot.

        Returns True if successful, False otherwise.
        """
        logger.info("Executing state rollback", app=app_package, type=experiment_type)
        if not snapshot_before:
            logger.warning("Empty snapshot, cannot execute rollback.")
            return False

        try:
            credentials = get_app_credentials(app_package)
            if experiment_type in ("aso_metadata", "play_store/update_listing"):
                lang = snapshot_before.get("language", "en-US")
                play_client = PlayStoreClient(credentials_path=credentials.google_credentials_path)
                res = play_client.update_listing(
                    package_name=app_package,
                    language=lang,
                    title=snapshot_before.get("title"),
                    short_description=snapshot_before.get("short_description"),
                    full_description=snapshot_before.get("full_description"),
                    video=snapshot_before.get("video"),
                )
                return res.success if hasattr(res, "success") else True

            elif experiment_type == "paywall_variant":
                logger.warning("RevenueCat offering rollback is not implemented")
                return False

            logger.warning("Unsupported experiment type for rollback", type=experiment_type)
            return False
        except Exception as e:
            logger.exception("Rollback failed", error=str(e))
            return False
