"""RevenueCat MCP Server - Main server implementation."""

from __future__ import annotations

import argparse
from contextlib import asynccontextmanager
from typing import Any, cast

import structlog
from mcp.server.fastmcp import FastMCP

from app_manager.credential_store import get_app_credentials
from mcp_gc_shared import configure_logging, load_dotenv
from revenuecat_mcp.client import RevenueCatClient, RevenueCatClientError

load_dotenv()

configure_logging("REVENUECAT_MCP")
logger = structlog.get_logger(__name__)


def get_client_from_context(package_name: str | None = None) -> RevenueCatClient:
    """Get a RevenueCatClient, optionally scoped to one app's own credentials.

    Each app in config/apps.json can define its own revenuecat_api_key /
    revenuecat_project_id. When package_name is given, resolve that app's
    credentials via the shared credential store and reuse a cached
    per-app client instead of the single global-.env client.

    Args:
        package_name: App package name to scope credentials to (optional).

    Returns:
        RevenueCatClient instance

    Raises:
        RevenueCatClientError: If no client/credentials are available
    """
    ctx = mcp.get_context()

    if not (hasattr(ctx, "request_context") and hasattr(ctx.request_context, "lifespan_context")):
        raise RevenueCatClientError(
            "RevenueCat client not initialized. Set REVENUECAT_API_KEY environment variable."
        )

    state = ctx.request_context.lifespan_context

    if package_name:
        creds = get_app_credentials(package_name)
        if not creds.revenuecat_api_key:
            raise RevenueCatClientError(
                f"No RevenueCat credentials configured for '{package_name}' "
                "(checked config/apps.json and the REVENUECAT_API_KEY env var)."
            )

        app_clients: dict[str, RevenueCatClient] = state.setdefault("app_clients", {})
        cached = app_clients.get(package_name)
        if cached is None:
            cached = RevenueCatClient(
                api_key=creds.revenuecat_api_key,
                project_id=creds.revenuecat_project_id,
            )
            app_clients[package_name] = cached
        return cached

    client: RevenueCatClient | None = state.get("client")
    if client is not None:
        return client

    raise RevenueCatClientError(
        "RevenueCat client not initialized. Set REVENUECAT_API_KEY environment variable."
    )


@asynccontextmanager
async def lifespan(_server: FastMCP):  # type: ignore[no-untyped-def]
    """Lifespan context manager for the MCP server."""
    logger.info("Initializing RevenueCat MCP Server")

    shared_state: dict[str, Any] = {"client": None}

    try:
        client = RevenueCatClient()
        logger.info("RevenueCat client initialized successfully")
        shared_state["client"] = client
    except RevenueCatClientError as e:
        logger.warning("RevenueCat client initialization failed", error=str(e))
        shared_state["client"] = None

    yield shared_state

    logger.info("Shutting down RevenueCat MCP Server")
    if shared_state.get("client") is not None:
        shared_state["client"].close()
    for app_client in shared_state.get("app_clients", {}).values():
        app_client.close()


# Initialize the MCP server
mcp = FastMCP(
    "RevenueCat MCP Server",
    lifespan=lifespan,
)


# =============================================================================
# Subscriber Tools
# =============================================================================


@mcp.tool()
def get_subscriber(app_user_id: str, package_name: str | None = None) -> dict[str, Any]:
    """Get subscriber information including entitlements, subscriptions, and purchase history.

    Args:
        app_user_id: The app user ID to look up in RevenueCat
        package_name: App package name to scope this call to that app's own
                      RevenueCat project (from config/apps.json). Omit to use
                      the server's default REVENUECAT_API_KEY/PROJECT_ID.

    Returns:
        Subscriber profile with active entitlements, subscription details, and purchase history
    """
    client = get_client_from_context(package_name)
    result = client.get_subscriber(app_user_id)
    return cast("dict[str, Any]", result.model_dump())


# =============================================================================
# Offerings Tools
# =============================================================================


@mcp.tool()
def list_offerings(package_name: str | None = None) -> list[dict[str, Any]]:
    """List all offerings configured in RevenueCat for this project.

    Args:
        package_name: App package name to scope this call to that app's own
                      RevenueCat project (from config/apps.json). Omit to use
                      the server's default REVENUECAT_API_KEY/PROJECT_ID.

    Returns:
        List of offerings with their packages and product configurations
    """
    client = get_client_from_context(package_name)
    offerings = client.list_offerings()
    return [o.model_dump() for o in offerings]


@mcp.tool()
def get_offering(offering_id: str, package_name: str | None = None) -> dict[str, Any]:
    """Get details of a specific RevenueCat offering.

    Args:
        offering_id: The offering identifier (e.g., 'default', 'premium')
        package_name: App package name to scope this call to that app's own
                      RevenueCat project (from config/apps.json). Omit to use
                      the server's default REVENUECAT_API_KEY/PROJECT_ID.

    Returns:
        Offering details with packages and metadata
    """
    client = get_client_from_context(package_name)
    result = client.get_offering(offering_id)
    return cast("dict[str, Any]", result.model_dump())


# =============================================================================
# Metrics Tools
# =============================================================================


@mcp.tool()
def get_overview_metrics(package_name: str | None = None) -> dict[str, Any]:
    """Get revenue overview metrics including MRR, active subscribers, trials, and churn rate.

    Args:
        package_name: App package name to scope this call to that app's own
                      RevenueCat project (from config/apps.json). Omit to use
                      the server's default REVENUECAT_API_KEY/PROJECT_ID.

    Returns:
        Overview metrics with MRR, subscriber counts, trial counts, churn and refund rates
    """
    client = get_client_from_context(package_name)
    result = client.get_overview_metrics()
    return cast("dict[str, Any]", result.model_dump())


@mcp.tool()
def get_charts(
    metric_name: str = "revenue",
    resolution: str = "day",
    start_date: str | None = None,
    end_date: str | None = None,
    package_name: str | None = None,
) -> dict[str, Any]:
    """Get chart data for revenue and subscriber metrics over time.

    Args:
        metric_name: Metric to chart - one of: revenue, mrr, active_subscribers,
                    new_subscribers, churn, active_trials, refund_rate
        resolution: Data resolution - one of: day, week, month
        start_date: Start date (YYYY-MM-DD). Defaults to 30 days ago.
        end_date: End date (YYYY-MM-DD). Defaults to today.
        package_name: App package name to scope this call to that app's own
                      RevenueCat project (from config/apps.json). Omit to use
                      the server's default REVENUECAT_API_KEY/PROJECT_ID.

    Returns:
        Time-series chart data with data points and total
    """
    client = get_client_from_context(package_name)
    result = client.get_charts(
        metric_name=metric_name,
        resolution=resolution,
        start_date=start_date,
        end_date=end_date,
    )
    return cast("dict[str, Any]", result.model_dump())


# =============================================================================
# Transaction Tools
# =============================================================================


@mcp.tool()
def get_transaction_history(
    app_user_id: str,
    limit: int = 100,
    package_name: str | None = None,
) -> list[dict[str, Any]]:
    """Get transaction history for a subscriber.

    Args:
        app_user_id: The app user ID
        limit: Maximum number of transactions to return (default: 100)
        package_name: App package name to scope this call to that app's own
                      RevenueCat project (from config/apps.json). Omit to use
                      the server's default REVENUECAT_API_KEY/PROJECT_ID.

    Returns:
        List of transactions including purchases, renewals, and refunds
    """
    client = get_client_from_context(package_name)
    transactions = client.get_transaction_history(app_user_id, limit)
    return [t.model_dump() for t in transactions]


# =============================================================================
# Entitlement Management Tools
# =============================================================================


@mcp.tool()
def grant_entitlement(
    app_user_id: str,
    entitlement_id: str,
    duration: str = "monthly",
    package_name: str | None = None,
) -> dict[str, Any]:
    """Grant a promotional entitlement to a user.

    Args:
        app_user_id: The app user ID to grant to
        entitlement_id: Entitlement identifier to grant
        duration: Duration of the grant - one of: daily, three_day, weekly, monthly,
                 two_month, three_month, six_month, yearly, lifetime
        package_name: App package name to scope this call to that app's own
                      RevenueCat project (from config/apps.json). Omit to use
                      the server's default REVENUECAT_API_KEY/PROJECT_ID.

    Returns:
        Grant result with success status
    """
    client = get_client_from_context(package_name)
    result = client.grant_entitlement(app_user_id, entitlement_id, duration)
    return cast("dict[str, Any]", result.model_dump())


@mcp.tool()
def revoke_entitlement(
    app_user_id: str,
    entitlement_id: str,
    package_name: str | None = None,
) -> dict[str, Any]:
    """Revoke a promotional entitlement from a user.

    Args:
        app_user_id: The app user ID to revoke from
        entitlement_id: Entitlement identifier to revoke
        package_name: App package name to scope this call to that app's own
                      RevenueCat project (from config/apps.json). Omit to use
                      the server's default REVENUECAT_API_KEY/PROJECT_ID.

    Returns:
        Revocation result with success status
    """
    client = get_client_from_context(package_name)
    result = client.revoke_entitlement(app_user_id, entitlement_id)
    return cast("dict[str, Any]", result.model_dump())


# =============================================================================
# Refund Tools
# =============================================================================


@mcp.tool()
def refund_purchase(
    app_user_id: str,
    store_transaction_id: str,
    package_name: str | None = None,
) -> dict[str, Any]:
    """Refund a purchase via RevenueCat.

    Args:
        app_user_id: The app user ID
        store_transaction_id: The store transaction identifier to refund
        package_name: App package name to scope this call to that app's own
                      RevenueCat project (from config/apps.json). Omit to use
                      the server's default REVENUECAT_API_KEY/PROJECT_ID.

    Returns:
        Refund result with success status
    """
    client = get_client_from_context(package_name)
    result = client.refund_purchase(app_user_id, store_transaction_id)
    return cast("dict[str, Any]", result.model_dump())


# =============================================================================
# Product Tools
# =============================================================================


@mcp.tool()
def list_products(package_name: str | None = None) -> list[dict[str, Any]]:
    """List all products configured in RevenueCat.

    Args:
        package_name: App package name to scope this call to that app's own
                      RevenueCat project (from config/apps.json). Omit to use
                      the server's default REVENUECAT_API_KEY/PROJECT_ID.

    Returns:
        List of products with their store identifiers and types
    """
    client = get_client_from_context(package_name)
    products = client.list_products()
    return [p.model_dump() for p in products]


@mcp.tool()
def create_offering(
    project_id: str | None = None,
    offering_config: dict[str, Any] | None = None,
    package_name: str | None = None,
) -> dict[str, Any]:
    """Create a new offering in RevenueCat.

    Args:
        project_id: RevenueCat project ID (optional, defaults to config)
        offering_config: Offering configuration dictionary
        package_name: App package name to scope this call to that app's own
                      RevenueCat project + API key (from config/apps.json).
                      Note the api_key must belong to the same project as
                      project_id — a mismatched pair will fail auth.
    """
    client = get_client_from_context(package_name)
    return cast(
        "dict[str, Any]",
        client.create_offering(project_id=project_id, offering_config=offering_config),
    )


@mcp.tool()
def update_offering(
    offering_id: str,
    updates: dict[str, Any],
    project_id: str | None = None,
    package_name: str | None = None,
) -> dict[str, Any]:
    """Update an offering in RevenueCat.

    Args:
        offering_id: The offering identifier
        updates: Dictionary of update fields
        project_id: RevenueCat project ID (optional)
        package_name: App package name to scope this call to that app's own
                      RevenueCat project + API key (from config/apps.json).
                      Note the api_key must belong to the same project as
                      project_id — a mismatched pair will fail auth.
    """
    client = get_client_from_context(package_name)
    return cast(
        "dict[str, Any]",
        client.update_offering(offering_id=offering_id, updates=updates, project_id=project_id),
    )


@mcp.tool()
def create_package(
    offering_id: str,
    package_config: dict[str, Any],
    project_id: str | None = None,
    package_name: str | None = None,
) -> dict[str, Any]:
    """Create a package under an offering in RevenueCat.

    Args:
        offering_id: The offering identifier
        package_config: Package configuration dictionary
        project_id: RevenueCat project ID (optional)
        package_name: App package name to scope this call to that app's own
                      RevenueCat project + API key (from config/apps.json).
                      Note the api_key must belong to the same project as
                      project_id — a mismatched pair will fail auth.
    """
    client = get_client_from_context(package_name)
    return cast(
        "dict[str, Any]",
        client.create_package(
            offering_id=offering_id, package_config=package_config, project_id=project_id
        ),
    )


@mcp.tool()
def attach_product(
    package_id: str,
    product_config: dict[str, Any],
    project_id: str | None = None,
    package_name: str | None = None,
) -> dict[str, Any]:
    """Attach a product to a package in RevenueCat.

    Args:
        package_id: The package identifier
        product_config: Product configuration dictionary
        project_id: RevenueCat project ID (optional)
        package_name: App package name to scope this call to that app's own
                      RevenueCat project + API key (from config/apps.json).
                      Note the api_key must belong to the same project as
                      project_id — a mismatched pair will fail auth.
    """
    client = get_client_from_context(package_name)
    return cast(
        "dict[str, Any]",
        client.attach_product(
            package_id=package_id, product_config=product_config, project_id=project_id
        ),
    )


# =============================================================================
# Server Entry Point
# =============================================================================


def main(argv: list[str] | None = None) -> None:
    """Run the RevenueCat MCP server."""
    parser = argparse.ArgumentParser(description="RevenueCat MCP Server")
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
        default=8001,
        help="Port for HTTP transport (default: 8001)",
    )

    args = parser.parse_args(argv)

    if args.transport == "streamable-http":
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")
