"""Analytics MCP Server - Main server implementation."""

from __future__ import annotations

import argparse
from contextlib import asynccontextmanager
from typing import Any

import structlog
from mcp.server.fastmcp import FastMCP

from analytics_mcp.client import AnalyticsClient, AnalyticsClientError
from mcp_gc_shared import configure_logging, load_dotenv

load_dotenv()

configure_logging("ANALYTICS_MCP")
logger = structlog.get_logger(__name__)


def get_client_from_context() -> AnalyticsClient:
    """Get AnalyticsClient from request context."""
    ctx = mcp.get_context()

    if hasattr(ctx, "request_context") and hasattr(ctx.request_context, "lifespan_context"):
        client: AnalyticsClient | None = ctx.request_context.lifespan_context.get("client")
        if client is not None:
            return client

    raise AnalyticsClientError(
        "Analytics client not initialized. Set GA4_PROPERTY_ID and "
        "GOOGLE_APPLICATION_CREDENTIALS environment variables."
    )


@asynccontextmanager
async def lifespan(_server: FastMCP):  # type: ignore[no-untyped-def]
    """Lifespan context manager for the MCP server."""
    logger.info("Initializing Analytics MCP Server")

    shared_state: dict[str, Any] = {"client": None}

    try:
        client = AnalyticsClient()
        logger.info("Analytics client initialized successfully")
        shared_state["client"] = client
    except AnalyticsClientError as e:
        logger.warning("Analytics client initialization failed", error=str(e))

    yield shared_state

    logger.info("Shutting down Analytics MCP Server")


# Initialize the MCP server
mcp = FastMCP(
    "Analytics MCP Server",
    lifespan=lifespan,
)


# =============================================================================
# Core Report Tools
# =============================================================================


@mcp.tool()
def run_report(
    dimensions: list[str],
    metrics: list[str],
    start_date: str = "30daysAgo",
    end_date: str = "today",
    limit: int = 100,
    order_by_metric: str | None = None,
) -> dict[str, Any]:
    """Run a custom GA4 analytics report with specified dimensions and metrics.

    Args:
        dimensions: List of GA4 dimension names (e.g., ['date', 'country', 'eventName'])
        metrics: List of GA4 metric names (e.g., ['activeUsers', 'sessions', 'totalRevenue'])
        start_date: Start date in YYYY-MM-DD or relative format (e.g., '30daysAgo', '7daysAgo')
        end_date: End date in YYYY-MM-DD or 'today'
        limit: Maximum number of rows to return (default: 100)
        order_by_metric: Optional metric name to sort results by (descending)

    Returns:
        Report with dimension/metric data rows
    """
    client = get_client_from_context()
    result = client.run_report(
        dimensions=dimensions,
        metrics=metrics,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        order_by_metric=order_by_metric,
    )
    return result.model_dump()


@mcp.tool()
def get_realtime_report(
    dimensions: list[str] | None = None,
    metrics: list[str] | None = None,
) -> dict[str, Any]:
    """Get real-time analytics data showing currently active users and their activity.

    Args:
        dimensions: Dimensions to break down by (default: ['unifiedScreenName'])
        metrics: Metrics to include (default: ['activeUsers'])

    Returns:
        Realtime report with current active users and activity breakdown
    """
    client = get_client_from_context()
    result = client.get_realtime_report(dimensions=dimensions, metrics=metrics)
    return result.model_dump()


# =============================================================================
# Pre-built Report Tools
# =============================================================================


@mcp.tool()
def get_active_users(
    start_date: str = "30daysAgo",
    end_date: str = "today",
) -> dict[str, Any]:
    """Get daily active users (DAU) over a date range with averages.

    Args:
        start_date: Start date (YYYY-MM-DD or relative like '30daysAgo')
        end_date: End date (YYYY-MM-DD or 'today')

    Returns:
        Active users report with daily DAU, total users, and average DAU
    """
    client = get_client_from_context()
    result = client.get_active_users(start_date=start_date, end_date=end_date)
    return result.model_dump()


@mcp.tool()
def get_user_acquisition(
    start_date: str = "30daysAgo",
    end_date: str = "today",
) -> dict[str, Any]:
    """Get user acquisition data broken down by channel (organic, paid, social, etc.).

    Args:
        start_date: Start date (YYYY-MM-DD or relative)
        end_date: End date (YYYY-MM-DD or 'today')

    Returns:
        Acquisition report with channels, new users, sessions, and engagement rates
    """
    client = get_client_from_context()
    result = client.get_user_acquisition(start_date=start_date, end_date=end_date)
    return result.model_dump()


@mcp.tool()
def get_retention(
    start_date: str = "30daysAgo",
    end_date: str = "today",
) -> dict[str, Any]:
    """Get user retention analysis showing new vs returning users over time.

    Args:
        start_date: Start date (YYYY-MM-DD or relative)
        end_date: End date (YYYY-MM-DD or 'today')

    Returns:
        Retention report with daily new/returning user breakdown and retention rates
    """
    client = get_client_from_context()
    result = client.get_retention(start_date=start_date, end_date=end_date)
    return result.model_dump()


@mcp.tool()
def get_events(
    start_date: str = "7daysAgo",
    end_date: str = "today",
    limit: int = 50,
    event_name_filter: str | None = None,
) -> dict[str, Any]:
    """Get top events by count with optional filtering.

    Args:
        start_date: Start date (YYYY-MM-DD or relative)
        end_date: End date (YYYY-MM-DD or 'today')
        limit: Maximum events to return (default: 50)
        event_name_filter: Optional filter to only show specific event name

    Returns:
        Event report with event names, counts, and user counts
    """
    client = get_client_from_context()
    result = client.get_events(
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        event_name_filter=event_name_filter,
    )
    return result.model_dump()


@mcp.tool()
def get_revenue_report(
    start_date: str = "30daysAgo",
    end_date: str = "today",
) -> dict[str, Any]:
    """Get revenue breakdown including in-app purchases, subscriptions, and ad revenue.

    Args:
        start_date: Start date (YYYY-MM-DD or relative)
        end_date: End date (YYYY-MM-DD or 'today')

    Returns:
        Revenue report with total, purchase, and ad revenue plus daily breakdown
    """
    client = get_client_from_context()
    result = client.get_revenue_report(start_date=start_date, end_date=end_date)
    return result.model_dump()


@mcp.tool()
def get_user_demographics(
    start_date: str = "30daysAgo",
    end_date: str = "today",
) -> dict[str, Any]:
    """Get user demographics including top countries, device categories, and OS versions.

    Args:
        start_date: Start date (YYYY-MM-DD or relative)
        end_date: End date (YYYY-MM-DD or 'today')

    Returns:
        Demographics report with country, device, and OS version breakdowns
    """
    client = get_client_from_context()
    result = client.get_user_demographics(start_date=start_date, end_date=end_date)
    return result.model_dump()


@mcp.tool()
def get_screen_views(
    start_date: str = "7daysAgo",
    end_date: str = "today",
    limit: int = 30,
) -> dict[str, Any]:
    """Get top screens/pages by view count.

    Args:
        start_date: Start date (YYYY-MM-DD or relative)
        end_date: End date (YYYY-MM-DD or 'today')
        limit: Maximum screens to return (default: 30)

    Returns:
        Screen view report with screen names, view counts, and user counts
    """
    client = get_client_from_context()
    result = client.get_screen_views(
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )
    return result.model_dump()


@mcp.tool()
def get_crash_events(
    start_date: str = "7daysAgo",
    end_date: str = "today",
) -> dict[str, Any]:
    """Get app crash/exception events from Analytics.

    Args:
        start_date: Start date (YYYY-MM-DD or relative)
        end_date: End date (YYYY-MM-DD or 'today')

    Returns:
        Crash events report with app_exception event data
    """
    client = get_client_from_context()
    result = client.get_crash_events(start_date=start_date, end_date=end_date)
    return result.model_dump()


# =============================================================================
# Server Entry Point
# =============================================================================


def main(argv: list[str] | None = None) -> None:
    """Run the Analytics MCP server."""
    parser = argparse.ArgumentParser(description="Analytics MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8002)

    args = parser.parse_args(argv)

    if args.transport == "streamable-http":
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")
