"""FCM Push Notification MCP Server."""

from __future__ import annotations

import argparse
from contextlib import asynccontextmanager
from typing import Any

import structlog
from mcp.server.fastmcp import FastMCP

from fcm_push_mcp.client import FCMClient, FCMClientError
from mcp_gc_shared import configure_logging, load_dotenv

load_dotenv()

configure_logging("FCM_PUSH_MCP")
logger = structlog.get_logger(__name__)


def get_client_from_context() -> FCMClient:
    """Get FCMClient from request context."""
    ctx = mcp.get_context()

    if hasattr(ctx, "request_context") and hasattr(ctx.request_context, "lifespan_context"):
        client: FCMClient | None = ctx.request_context.lifespan_context.get("client")
        if client is not None:
            return client

    raise FCMClientError("FCM client not initialized.")


@asynccontextmanager
async def lifespan(_server: FastMCP):  # type: ignore[no-untyped-def]
    """Lifespan context manager for the MCP server."""
    logger.info("Initializing FCM Push MCP Server")

    shared_state: dict[str, Any] = {"client": None}

    try:
        client = FCMClient()
        logger.info("FCM client initialized successfully")
        shared_state["client"] = client
    except Exception as e:
        logger.warning("FCM client initialization failed", error=str(e))

    yield shared_state

    logger.info("Shutting down FCM Push MCP Server")


# Initialize the MCP server
mcp = FastMCP(
    "FCM Push MCP Server",
    lifespan=lifespan,
)


@mcp.tool()
def send_push_notification(
    topic: str,
    title: str,
    body: str,
    data: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Send a push notification to all users subscribed to a specific FCM topic.

    Args:
        topic: The topic name to broadcast to (e.g. 'new_features', 'promotions')
        title: The notification title to show on device
        body: The main description/alert body text
        data: Optional key-value pairs of custom payload data
    """
    client = get_client_from_context()
    return client.send_push_notification(topic=topic, title=title, body=body, data=data)


@mcp.tool()
def send_push_to_token(
    token: str,
    title: str,
    body: str,
    data: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Send a direct push notification to an individual device registration token.

    Args:
        token: Unique FCM device registration token
        title: The notification title to show on device
        body: The main description/alert body text
        data: Optional key-value pairs of custom payload data
    """
    client = get_client_from_context()
    return client.send_push_to_token(token=token, title=title, body=body, data=data)


@mcp.tool()
def send_push_to_condition(
    condition: str,
    title: str,
    body: str,
    data: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Send a push notification to users matching a conditional logic topic expression.

    Args:
        condition: Expression targeting topics (e.g. "'trial_expired' in topics && 'in' in topics")
        title: The notification title to show on device
        body: The main description/alert body text
        data: Optional key-value pairs of custom payload data
    """
    client = get_client_from_context()
    return client.send_push_to_condition(condition=condition, title=title, body=body, data=data)


def main(argv: list[str] | None = None) -> None:
    """Run the FCM Push MCP server."""
    parser = argparse.ArgumentParser(description="FCM Push MCP Server")
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
        default=8006,
        help="Port for HTTP transport (default: 8006)",
    )

    args = parser.parse_args(argv)

    if args.transport == "streamable-http":
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")
