"""Google Cloud Storage MCP Server - Main server implementation."""

from __future__ import annotations

import base64
import binascii
import json
from contextlib import asynccontextmanager
from typing import Any

import structlog
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from mcp_gc_shared import configure_logging, load_dotenv

load_dotenv()

from gcs_mcp.client import GCSClient, GCSClientError

configure_logging("GCS_MCP")
logger = structlog.get_logger(__name__)


def get_client_from_context() -> GCSClient:
    """Get GCSClient from request context.

    Returns:
        GCSClient instance
    """
    ctx = mcp.get_context()

    # Check for per-request credentials in headers
    if hasattr(ctx, "request_context") and hasattr(ctx.request_context, "request"):
        request = ctx.request_context.request
        if request is not None and hasattr(request, "headers"):
            headers = request.headers

            if "x-google-credentials" in headers:
                creds_str = headers["x-google-credentials"]
                try:
                    creds_json = json.loads(creds_str)
                    return GCSClient(credentials_json=creds_json)
                except json.JSONDecodeError as e:
                    raise GCSClientError(f"Invalid JSON in X-Google-Credentials header: {e}")

            if "x-google-credentials-base64" in headers:
                creds_b64 = headers["x-google-credentials-base64"]
                try:
                    creds_bytes = base64.b64decode(creds_b64)
                    creds_str = creds_bytes.decode("utf-8")
                    creds_json = json.loads(creds_str)
                    return GCSClient(credentials_json=creds_json)
                except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as e:
                    raise GCSClientError(
                        f"Invalid base64 or JSON in X-Google-Credentials-Base64 header: {e}"
                    )

    # Fall back to shared client from lifespan
    if hasattr(ctx, "request_context") and hasattr(ctx.request_context, "lifespan_context"):
        client: GCSClient | None = ctx.request_context.lifespan_context.get("client")
        if client is not None:
            return client

    raise GCSClientError(
        "No credentials provided. Set X-Google-Credentials or configure GOOGLE_PLAY_STORE_CREDENTIALS."
    )


@asynccontextmanager
async def lifespan(_server: FastMCP):  # type: ignore[no-untyped-def]
    """Lifespan context manager for the MCP server."""
    logger.info("Initializing GCS MCP Server")

    shared_state: dict[str, Any] = {"client": None}

    try:
        client = GCSClient()
        _ = client._get_client()
        logger.info("GCS client initialized successfully")
        shared_state["client"] = client
    except GCSClientError as e:
        logger.warning("GCS client initialization failed", error=str(e))
        shared_state["client"] = None

    _server._shared_state = shared_state  # type: ignore[attr-defined]

    yield shared_state
    logger.info("Shutting down GCS MCP Server")


# Initialize the MCP server
mcp = FastMCP(
    "GCS MCP Server",
    lifespan=lifespan,
    transport_security=TransportSecuritySettings(),
)


@mcp.tool()
def list_buckets() -> list[dict[str, Any]]:
    """List all buckets in the Google Cloud Storage project.

    Returns:
        List of buckets.
    """
    client = get_client_from_context()
    return client.list_buckets()


@mcp.tool()
def list_blobs(bucket_name: str, prefix: str = "") -> list[dict[str, Any]]:
    """List blobs (files) in a specific GCS bucket.

    Args:
        bucket_name: Name of the GCS bucket.
        prefix: Optional prefix to filter files (e.g. folder path).

    Returns:
        List of blobs.
    """
    client = get_client_from_context()
    return client.list_blobs(bucket_name, prefix)


@mcp.tool()
def read_blob_content(bucket_name: str, blob_name: str) -> str:
    """Read the content of a blob into memory as a string.

    Ideal for text files or CSVs.

    Args:
        bucket_name: Name of the GCS bucket.
        blob_name: Name of the blob to read.

    Returns:
        String content of the blob.
    """
    client = get_client_from_context()
    return client.read_blob_content(bucket_name, blob_name)


@mcp.tool()
def download_blob(bucket_name: str, blob_name: str, destination_path: str) -> dict[str, Any]:
    """Download a blob from GCS to a local file.

    Args:
        bucket_name: Name of the GCS bucket.
        blob_name: Name of the blob to download.
        destination_path: Local path to save the file.

    Returns:
        Dictionary with success status.
    """
    client = get_client_from_context()
    return client.download_blob(bucket_name, blob_name, destination_path)
