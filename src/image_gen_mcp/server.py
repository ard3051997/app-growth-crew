"""Image Generation MCP Server (Gemini native image models)."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

import structlog
from mcp.server.fastmcp import FastMCP

from image_gen_mcp.client import ImageGenClient, ImageGenClientError
from mcp_gc_shared import configure_logging, load_dotenv

load_dotenv()

configure_logging("IMAGE_GEN_MCP")
logger = structlog.get_logger(__name__)


def get_client_from_context() -> ImageGenClient:
    """Get ImageGenClient from request context."""
    ctx = mcp.get_context()

    if hasattr(ctx, "request_context") and hasattr(ctx.request_context, "lifespan_context"):
        client: ImageGenClient | None = ctx.request_context.lifespan_context.get("client")
        if client is not None:
            return client

    raise ImageGenClientError("Image generation client not initialized. Set GEMINI_API_KEY.")


@asynccontextmanager
async def lifespan(_server: FastMCP):  # type: ignore[no-untyped-def]
    """Lifespan context manager."""
    logger.info("Initializing Image Generation MCP Server")

    shared_state: dict[str, Any] = {"client": None}

    try:
        client = ImageGenClient(api_key=os.environ.get("GEMINI_API_KEY", ""))
        logger.info("Image generation client initialized successfully")
        shared_state["client"] = client
    except ImageGenClientError as e:
        logger.warning("Image generation client initialization failed", error=str(e))

    yield shared_state

    logger.info("Shutting down Image Generation MCP Server")


mcp = FastMCP(
    "Image Generation MCP Server",
    lifespan=lifespan,
)


@mcp.tool()
def generate_image(
    prompt: str,
    save_path: str | None = None,
) -> dict[str, Any]:
    """Generate a creative image (e.g. an App Store screenshot concept or icon draft) from a text prompt.

    Returns the real generated image (base64-encoded PNG) or raises a clear
    error -- never fabricates an image or a success result.

    Args:
        prompt: Description of the image to generate.
        save_path: Optional local file path to also save the raw image bytes to.
    """
    client = get_client_from_context()
    return client.generate_image(prompt, save_path=save_path)
