"""AdMob MCP Server - Main server implementation."""

from __future__ import annotations

import argparse
from contextlib import asynccontextmanager
from typing import Any, cast

import structlog
from mcp.server.fastmcp import FastMCP

from admob_mcp.client import AdMobClient, AdMobClientError
from mcp_gc_shared import configure_logging, load_dotenv

load_dotenv()

configure_logging("ADMOB_MCP")
logger = structlog.get_logger(__name__)


def get_client_from_context() -> AdMobClient:
    """Get AdMobClient from request context."""
    ctx = mcp.get_context()

    if hasattr(ctx, "request_context") and hasattr(ctx.request_context, "lifespan_context"):
        client: AdMobClient | None = ctx.request_context.lifespan_context.get("client")
        if client is not None:
            return client

    raise AdMobClientError(
        "AdMob client not initialized. Set ADMOB_ACCOUNT_ID and "
        "GOOGLE_APPLICATION_CREDENTIALS environment variables."
    )


@asynccontextmanager
async def lifespan(_server: FastMCP):  # type: ignore[no-untyped-def]
    """Lifespan context manager."""
    logger.info("Initializing AdMob MCP Server")

    shared_state: dict[str, Any] = {"client": None}

    try:
        client = AdMobClient()
        logger.info("AdMob client initialized successfully")
        shared_state["client"] = client
    except AdMobClientError as e:
        logger.warning("AdMob client initialization failed", error=str(e))

    yield shared_state

    logger.info("Shutting down AdMob MCP Server")


mcp = FastMCP(
    "AdMob MCP Server",
    lifespan=lifespan,
)


# =============================================================================
# Account Tools
# =============================================================================


@mcp.tool()
def list_accounts() -> list[dict[str, Any]]:
    """List all AdMob accounts accessible with current credentials.

    Returns:
        List of AdMob accounts with IDs, names, and settings
    """
    client = get_client_from_context()
    accounts = client.list_accounts()
    return [a.model_dump() for a in accounts]


@mcp.tool()
def get_account() -> dict[str, Any]:
    """Get details for the configured AdMob account.

    Returns:
        Account details including publisher ID, timezone, and currency
    """
    client = get_client_from_context()
    result = client.get_account()
    return cast("dict[str, Any]", result.model_dump())


# =============================================================================
# Ad Unit Tools
# =============================================================================


@mcp.tool()
def list_ad_units() -> list[dict[str, Any]]:
    """List all ad units for the AdMob account.

    Returns:
        List of ad units with IDs, names, formats, and associated apps
    """
    client = get_client_from_context()
    units = client.list_ad_units()
    return [u.model_dump() for u in units]


@mcp.tool()
def get_ad_unit(ad_unit_id: str) -> dict[str, Any]:
    """Get details of a specific ad unit.

    Args:
        ad_unit_id: The ad unit ID to look up

    Returns:
        Ad unit details including format, types, and associated app
    """
    client = get_client_from_context()
    result = client.get_ad_unit(ad_unit_id)
    return cast("dict[str, Any]", result.model_dump())


# =============================================================================
# App Tools
# =============================================================================


@mcp.tool()
def list_apps() -> list[dict[str, Any]]:
    """List all apps linked to the AdMob account.

    Returns:
        List of apps with IDs, names, platforms, and store links
    """
    client = get_client_from_context()
    apps = client.list_apps()
    return [a.model_dump() for a in apps]


# =============================================================================
# Report Tools
# =============================================================================


@mcp.tool()
def get_network_report(
    start_date: str | None = None,
    end_date: str | None = None,
    dimensions: list[str] | None = None,
    metrics: list[str] | None = None,
) -> dict[str, Any]:
    """Generate a network-level ad revenue report.

    Args:
        start_date: Start date (YYYY-MM-DD). Defaults to 30 days ago.
        end_date: End date (YYYY-MM-DD). Defaults to today.
        dimensions: Report dimensions (default: ['DATE']). Options: DATE, MONTH,
                   WEEK, AD_UNIT, APP, AD_TYPE, COUNTRY, FORMAT, PLATFORM
        metrics: Report metrics (default: ['ESTIMATED_EARNINGS', 'IMPRESSIONS',
                'CLICKS', 'AD_REQUESTS', 'MATCHED_REQUESTS'])

    Returns:
        Network report with earnings, impressions, clicks per dimension
    """
    client = get_client_from_context()
    result = client.get_network_report(
        start_date=start_date,
        end_date=end_date,
        dimensions=dimensions,
        metrics=metrics,
    )
    return cast("dict[str, Any]", result.model_dump())


@mcp.tool()
def get_mediation_report(
    start_date: str | None = None,
    end_date: str | None = None,
    dimensions: list[str] | None = None,
    metrics: list[str] | None = None,
) -> dict[str, Any]:
    """Generate a mediation ad revenue report showing performance by ad source.

    Args:
        start_date: Start date (YYYY-MM-DD). Defaults to 30 days ago.
        end_date: End date (YYYY-MM-DD). Defaults to today.
        dimensions: Report dimensions (default: ['DATE'])
        metrics: Report metrics (default: ['ESTIMATED_EARNINGS', 'IMPRESSIONS', 'MATCHED_REQUESTS'])

    Returns:
        Mediation report with earnings by ad network/source
    """
    client = get_client_from_context()
    result = client.get_mediation_report(
        start_date=start_date,
        end_date=end_date,
        dimensions=dimensions,
        metrics=metrics,
    )
    return cast("dict[str, Any]", result.model_dump())


@mcp.tool()
def get_earnings_summary() -> dict[str, Any]:
    """Get summarized ad earnings across multiple time periods.

    Returns:
        Earnings summary with today, yesterday, 7-day, 30-day totals,
        plus today's impressions, clicks, and eCPM
    """
    client = get_client_from_context()
    result = client.get_earnings_summary()
    return cast("dict[str, Any]", result.model_dump())


# =============================================================================
# Entry Point
# =============================================================================


def main(argv: list[str] | None = None) -> None:
    """Run the AdMob MCP server."""
    parser = argparse.ArgumentParser(description="AdMob MCP Server")
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8003)

    args = parser.parse_args(argv)

    if args.transport == "streamable-http":
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")
