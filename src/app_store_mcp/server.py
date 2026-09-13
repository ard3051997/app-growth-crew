"""App Store Connect MCP Server."""

from __future__ import annotations

import argparse
from contextlib import asynccontextmanager
from typing import Any

import structlog
from mcp.server.fastmcp import FastMCP

from app_store_mcp.client import AppStoreClient, AppStoreClientError
from mcp_gc_shared import configure_logging, load_dotenv

load_dotenv()

configure_logging("APP_STORE_MCP")
logger = structlog.get_logger(__name__)


def get_client_from_context() -> AppStoreClient:
    """Get AppStoreClient from request context."""
    ctx = mcp.get_context()

    if hasattr(ctx, "request_context") and hasattr(ctx.request_context, "lifespan_context"):
        client: AppStoreClient | None = ctx.request_context.lifespan_context.get("client")
        if client is not None:
            return client

    raise AppStoreClientError("App Store client not initialized.")


@asynccontextmanager
async def lifespan(_server: FastMCP):  # type: ignore[no-untyped-def]
    """Lifespan context manager for the MCP server."""
    logger.info("Initializing App Store MCP Server")

    shared_state: dict[str, Any] = {"client": None}

    try:
        client = AppStoreClient()
        logger.info("App Store client initialized successfully")
        shared_state["client"] = client
    except Exception as e:
        logger.warning("App Store client initialization failed", error=str(e))

    yield shared_state

    logger.info("Shutting down App Store MCP Server")


# Initialize the MCP server
mcp = FastMCP(
    "App Store MCP Server",
    lifespan=lifespan,
)


@mcp.tool()
def get_app_details(
    bundle_id: str,
    language: str = "en-US",
) -> dict[str, Any]:
    """Retrieve details for an iOS app from the App Store including title, descriptions, rating.

    Args:
        bundle_id: Bundle ID (e.g. 'com.example.app') or numeric App Store Track ID (e.g. '123456789')
        language: Language code for listing localized details
    """
    client = get_client_from_context()
    return client.get_app_details(bundle_id=bundle_id, language=language)


@mcp.tool()
def get_reviews(
    bundle_id: str,
    max_results: int = 50,
    profile: str | None = None,
) -> list[dict[str, Any]]:
    """Retrieve the most recent reviews for an iOS app from the App Store.

    Uses the authenticated App Store Connect API, so review_id values are
    real and usable with reply_to_review.

    Args:
        bundle_id: Bundle ID or numeric App Store Track ID
        max_results: Maximum reviews to fetch (default: 50)
        profile: Optional named asc auth profile
    """
    client = get_client_from_context()
    return client.get_reviews(bundle_id=bundle_id, max_results=max_results, profile=profile)


@mcp.tool()
def reply_to_review(
    review_id: str,
    reply_text: str,
    profile: str | None = None,
) -> dict[str, Any]:
    """Post a developer response to an iOS customer review.

    The response is publicly visible to all App Store users and replaces
    any existing response to the same review -- this is a real, irreversible
    public action, not a draft.

    Args:
        review_id: Review ID to reply to (from get_reviews)
        reply_text: Response text visible to the reviewer and all App Store users
        profile: Optional named asc auth profile
    """
    client = get_client_from_context()
    return client.reply_to_review(review_id=review_id, reply_text=reply_text, profile=profile)


@mcp.tool()
def get_keyword_rank(
    bundle_id: str,
    keyword: str,
    country: str = "us",
    limit: int = 200,
) -> dict[str, Any]:
    """Find an app's real current App Store search rank for a keyword.

    Uses the public iTunes Search API — the same results a real user searching
    the App Store would see. Useful as a baseline for apps with too little
    install volume for a conversion-rate baseline to be meaningful.

    Args:
        bundle_id: Bundle ID or numeric App Store Connect app ID
        keyword: Search term to rank against
        country: Storefront country code (default: us)
        limit: How many results to scan (default: 200)
    """
    client = get_client_from_context()
    return client.get_keyword_rank(
        bundle_id=bundle_id, keyword=keyword, country=country, limit=limit
    )


@mcp.tool()
def update_listing(
    bundle_id: str,
    title: str | None = None,
    short_description: str | None = None,
    full_description: str | None = None,
    locale: str = "en-US",
    profile: str | None = None,
) -> dict[str, Any]:
    """Update metadata fields (title, descriptions) for an iOS app on App Store Connect.

    Calls the real App Store Connect API via the `asc` CLI (see `asc doctor` for
    configured auth profiles) — this makes a real, live change to the app's listing.

    Args:
        bundle_id: Bundle ID or numeric App Store Connect app ID
        title: Optional new app name (App Info field)
        short_description: Optional new subtitle (App Info field)
        full_description: Optional new app store version description
        locale: Locale to update (default: en-US — use the app's actual listing
            locale, e.g. 'en-GB', if it differs)
        profile: Optional named asc auth profile; omit to use asc's default
    """
    client = get_client_from_context()
    return client.update_listing(
        bundle_id=bundle_id,
        title=title,
        short_description=short_description,
        full_description=full_description,
        locale=locale,
        profile=profile,
    )


def main(argv: list[str] | None = None) -> None:
    """Run the App Store MCP server."""
    parser = argparse.ArgumentParser(description="App Store MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="Transport type (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host for HTTP transport (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8007,
        help="Port for HTTP transport (default: 8007)",
    )

    args = parser.parse_args(argv)

    if args.transport == "streamable-http":
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")
