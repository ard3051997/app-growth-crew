"""Journey Map MCP Server — generates interactive journey_map.html from EVENTS.md + live data."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import structlog
from mcp.server.fastmcp import FastMCP

from journey_map_mcp.generator import (
    generate_journey_map as _generate,
)
from journey_map_mcp.generator import (
    get_journey_structure as _structure,
)
from journey_map_mcp.generator import (
    parse_events_md as _parse,
)
from mcp_gc_shared import configure_logging, load_dotenv

load_dotenv()

configure_logging("JOURNEY_MAP_MCP")
logger = structlog.get_logger(__name__)

mcp = FastMCP("Journey Map MCP")

_DEFAULT_EVENTS_MD_PATH = Path(__file__).parent.parent.parent / "docs" / "EVENTS.md"
if not _DEFAULT_EVENTS_MD_PATH.exists():
    _DEFAULT_EVENTS_MD_PATH = Path(__file__).parent.parent.parent / "EVENTS.md"
_DEFAULT_EVENTS_MD = str(_DEFAULT_EVENTS_MD_PATH)
_DEFAULT_OUTPUT = str(Path(__file__).parent.parent.parent / "journey_map.html")


@asynccontextmanager
async def lifespan(_server: FastMCP):  # type: ignore[no-untyped-def]
    logger.info("Initializing Journey Map MCP Server")
    yield {}
    logger.info("Shutting down Journey Map MCP Server")


mcp = FastMCP("Journey Map MCP", lifespan=lifespan)


@mcp.tool()
def parse_events_md(
    events_md_path: str = _DEFAULT_EVENTS_MD,
) -> dict[str, Any]:
    """Parse EVENTS.md and return all journey definitions as structured JSON.

    Returns a dict keyed by journey number. Each journey contains its title,
    description, and sections (table blocks with step/event/branch/next columns).

    Args:
        events_md_path: Path to EVENTS.md. Defaults to repo root EVENTS.md.
    """
    logger.info("Parsing EVENTS.md", path=events_md_path)
    journeys = _parse(events_md_path)
    return {
        "journey_count": len(journeys),
        "journeys": {str(k): v for k, v in journeys.items()},
    }


@mcp.tool()
def get_journey_structure(
    events_md_path: str = _DEFAULT_EVENTS_MD,
) -> dict[str, Any]:
    """Return a lightweight summary of EVENTS.md — journey titles, GA4 events, source files.

    Does NOT make any API calls. Use this to understand what flows are defined
    before triggering a full generation.

    Args:
        events_md_path: Path to EVENTS.md. Defaults to repo root EVENTS.md.
    """
    logger.info("Reading journey structure", path=events_md_path)
    return _structure(events_md_path)


@mcp.tool()
def generate_journey_map(
    package_name: str = "",
    events_md_path: str = _DEFAULT_EVENTS_MD,
    output_path: str = _DEFAULT_OUTPUT,
    date_range_days: int = 30,
    app_name: str = "",
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Generate or refresh journey_map.html with live funnel data + EVENTS.md structure.

    Pipeline:
    1. Fetches funnel analysis from funnel_engine_mcp (30d + 7d).
    2. Parses EVENTS.md for all 15 journeys, stages, and branches.
    3. Fetches GCS Play Console stats (installs, traffic sources, countries).
    4. Injects all data into the HTML template and writes the output file.

    Args:
        package_name: Android package name. Defaults to APP_PACKAGE_NAME env var.
        events_md_path: Path to EVENTS.md file.
        output_path: Where to write the generated HTML. Defaults to repo root journey_map.html.
        date_range_days: Primary date range for funnel data (7 or 30). Default 30.
        app_name: Display name for the app. Defaults to package name last segment.
        force_refresh: If True, re-fetches funnel data even if cache exists.

    Returns:
        Summary with output_path, journey_count, health_score, total_revenue_impact,
        gcs_stats_available.
    """
    pkg = package_name or os.environ.get("APP_PACKAGE_NAME", "")
    if not pkg:
        return {"error": "package_name is required. Set APP_PACKAGE_NAME or pass it explicitly."}

    logger.info(
        "Generating journey map",
        package_name=pkg,
        date_range_days=date_range_days,
        force_refresh=force_refresh,
    )

    try:
        result = _generate(
            package_name=pkg,
            events_md_path=events_md_path,
            output_path=output_path,
            date_range_days=date_range_days,
            app_name=app_name or None,
            force_refresh=force_refresh,
        )
        logger.info(
            "Journey map generated",
            output=result["output_path"],
            journeys=result["journey_count"],
            health_score=result["health_score"],
        )
        return result
    except Exception as e:
        logger.exception("Journey map generation failed", error=str(e))
        return {"error": str(e)}
