"""ASO Keyword MCP Server - Main server implementation."""

from __future__ import annotations

import argparse
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import structlog
from mcp.server.fastmcp import FastMCP

from aso_keyword_mcp.client import ASOClient, ASOClientError
from mcp_gc_shared import configure_logging, load_dotenv

load_dotenv()

configure_logging("ASO_MCP")
logger = structlog.get_logger(__name__)


def get_client_from_context() -> ASOClient:
    """Get ASOClient from request context."""
    ctx = mcp.get_context()

    if hasattr(ctx, "request_context") and hasattr(ctx.request_context, "lifespan_context"):
        client: ASOClient | None = ctx.request_context.lifespan_context.get("client")
        if client is not None:
            return client

    raise ASOClientError("ASO client not initialized.")


@asynccontextmanager
async def lifespan(_server: FastMCP):  # type: ignore[no-untyped-def]
    """Lifespan context manager."""
    logger.info("Initializing ASO Keyword MCP Server")

    shared_state: dict[str, Any] = {"client": None}

    try:
        client = ASOClient()
        logger.info("ASO client initialized successfully")
        shared_state["client"] = client
    except ASOClientError as e:
        logger.warning("ASO client initialization failed", error=str(e))

    yield shared_state

    logger.info("Shutting down ASO Keyword MCP Server")


mcp = FastMCP(
    "ASO Keyword MCP Server",
    lifespan=lifespan,
)


# =============================================================================
# Keyword Research Tools
# =============================================================================


@mcp.tool()
def search_keywords(
    seed_keyword: str,
    language: str = "en",
    country: str = "us",
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Search for keyword suggestions related to a seed term using Google Play data.

    Args:
        seed_keyword: Starting keyword to find related suggestions (e.g., 'task manager')
        language: Language code (default: en)
        country: Country code (default: us)
        limit: Maximum results to return (default: 20)

    Returns:
        List of keyword suggestions with estimated volume, difficulty, and relevance scores
    """
    client = get_client_from_context()
    results = client.search_keywords(seed_keyword, language, country, limit)
    return [r.model_dump() for r in results]


@mcp.tool()
def get_keyword_difficulty(
    keyword: str,
    language: str = "en",
    country: str = "us",
) -> dict[str, Any]:
    """Estimate keyword difficulty and competition for a specific keyword.

    Args:
        keyword: The keyword to analyze (e.g., 'photo editor')
        language: Language code (default: en)
        country: Country code (default: us)

    Returns:
        Difficulty score (0-100), label (Easy/Medium/Hard/Very Hard), and top competing apps
    """
    client = get_client_from_context()
    result = client.get_keyword_difficulty(keyword, language, country)
    return result.model_dump()


@mcp.tool()
def get_keyword_volume(
    keywords: list[str],
    language: str = "en",
    country: str = "us",
) -> list[dict[str, Any]]:
    """Estimate search volume for multiple keywords.

    Args:
        keywords: List of keywords to analyze (e.g., ['photo editor', 'image crop'])
        language: Language code (default: en)
        country: Country code (default: us)

    Returns:
        Volume estimates with trend and competition level for each keyword
    """
    client = get_client_from_context()
    results = client.get_keyword_volume(keywords, language, country)
    return [r.model_dump() for r in results]


@mcp.tool()
def get_advanced_keyword_difficulty(
    keyword: str,
    country: str = "us",
    limit: int = 50,
) -> dict[str, Any]:
    """Multi-factor difficulty/traffic/opportunity scoring for a keyword (0-100 scale).

    A more detailed alternative to get_keyword_difficulty: difficulty combines title
    competition, competitor strength, install barrier, and publisher authority;
    traffic combines search depth, top-app installs, an autocomplete heuristic, and
    keyword characteristics; opportunity is traffic weighted by inverse difficulty.

    Args:
        keyword: The keyword to analyze (e.g., 'photo editor')
        country: Country code (default: us)
        limit: Number of competing apps to sample (default: 50)

    Returns:
        Difficulty, traffic, and opportunity scores (0-100) with component breakdowns
        and a human-readable recommendation.
    """
    client = get_client_from_context()
    result = client.get_advanced_keyword_difficulty(keyword, country, limit)
    return result.model_dump()


# =============================================================================
# App Keyword Analysis Tools
# =============================================================================


@mcp.tool()
def get_app_keywords(
    package_name: str,
    language: str = "en",
    country: str = "us",
) -> dict[str, Any]:
    """Extract and analyze keywords from an app's current store listing.

    Args:
        package_name: App package name (e.g., com.example.myapp)
        language: Language code (default: en)
        country: Country code (default: us)

    Returns:
        Extracted keywords from title and description with relevance scores
    """
    client = get_client_from_context()
    result = client.get_app_keywords(package_name, language, country)
    return result.model_dump()


@mcp.tool()
def get_competitor_keywords(
    package_name: str,
    competitor_package: str,
    language: str = "en",
    country: str = "us",
) -> dict[str, Any]:
    """Analyze competitor keywords and find keyword gap opportunities.

    Args:
        package_name: Your app package name
        competitor_package: Competitor app package name to compare against
        language: Language code (default: en)
        country: Country code (default: us)

    Returns:
        Shared keywords, unique competitor keywords, and keyword gap opportunities
    """
    client = get_client_from_context()
    result = client.get_competitor_keywords(package_name, competitor_package, language, country)
    return result.model_dump()


# =============================================================================
# Ranking & Category Tools
# =============================================================================


@mcp.tool()
def track_keyword_ranking(
    keyword: str,
    package_name: str,
    language: str = "en",
    country: str = "us",
) -> dict[str, Any]:
    """Check the current ranking position of an app for a specific keyword.

    Args:
        keyword: Keyword to check ranking for
        package_name: App package name to find in results
        language: Language code (default: en)
        country: Country code (default: us)

    Returns:
        Ranking position, whether app was found, and total result count
    """
    client = get_client_from_context()
    result = client.track_keyword_ranking(keyword, package_name, language, country)
    return result.model_dump()


@mcp.tool()
def get_category_top_apps(
    category: str,
    language: str = "en",
    country: str = "us",
    limit: int = 30,
) -> list[dict[str, Any]]:
    """Get top-ranked apps in a Google Play Store category.

    Args:
        category: Play Store category (e.g., 'PRODUCTIVITY', 'GAME_ACTION', 'TOOLS')
        language: Language code (default: en)
        country: Country code (default: us)
        limit: Maximum apps to return (default: 30)

    Returns:
        Top apps with rank, title, rating, installs, and developer info
    """
    client = get_client_from_context()
    apps = client.get_category_top_apps(category, language, country, limit)
    return [a.model_dump() for a in apps]


# =============================================================================
# ASO Optimization Tools
# =============================================================================


@mcp.tool()
def analyze_listing_aso(
    package_name: str,
    language: str = "en",
    country: str = "us",
) -> dict[str, Any]:
    """Analyze the ASO (App Store Optimization) quality of a store listing.

    Args:
        package_name: App package name to analyze
        language: Language code (default: en)
        country: Country code (default: us)

    Returns:
        Overall ASO score (0-100), title/description scores, keyword density,
        and specific improvement recommendations
    """
    client = get_client_from_context()
    result = client.analyze_listing_aso(package_name, language, country)
    return result.model_dump()


@mcp.tool()
def generate_optimized_listing(
    package_name: str,
    target_keywords: list[str] | None = None,
    language: str = "en",
    country: str = "us",
) -> dict[str, Any]:
    """Generate ASO-optimized store listing suggestions.

    Generates optimized title, short description, and full description.

    Args:
        package_name: App package name to optimize
        target_keywords: Optional list of target keywords to incorporate. If not provided,
                        keywords will be auto-detected from the current listing.
        language: Language code (default: en)
        country: Country code (default: us)

    Returns:
        Optimized title, short description, and description suggestions with
        improvement notes and target keywords
    """
    client = get_client_from_context()
    result = client.generate_optimized_listing(package_name, target_keywords, language, country)
    return result.model_dump()


# =============================================================================
# AutoASO Engine Wrappers
# =============================================================================


@mcp.tool()
def prepare_auto_aso_keywords(
    keywords_file_path: str,
) -> dict[str, Any]:
    """Sync volume and difficulty metrics for keywords via the AutoASO prepare script (using AppFollow).

    Args:
        keywords_file_path: Absolute path to the keywords YAML file (e.g. /path/to/keywords.yaml)

    Returns:
        Result with success status and script output
    """
    import subprocess

    auto_aso_dir = os.environ.get("AUTO_ASO_DIR", "/Volumes/Crucial X9/Code/AutoASO")
    prepare_script = Path(auto_aso_dir) / "prepare.py"

    if not prepare_script.exists():
        return {"success": False, "error": f"AutoASO prepare script not found at {prepare_script}"}

    env = os.environ.copy()

    try:
        result = subprocess.run(  # noqa: S603
            [sys.executable, prepare_script, "--keywords", keywords_file_path],
            capture_output=True,
            text=True,
            check=True,
            env=env,
            cwd=auto_aso_dir,
        )
        return {
            "success": True,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except subprocess.CalledProcessError as e:
        return {
            "success": False,
            "error": f"Prepare script failed with exit code {e.returncode}",
            "stdout": e.stdout,
            "stderr": e.stderr,
        }


@mcp.tool()
def score_auto_aso_metadata(
    metadata_file_path: str,
    keywords_file_path: str,
) -> dict[str, Any]:
    """Score store listing metadata against keywords using the AutoASO scoring engine.

    Args:
        metadata_file_path: Absolute path to the metadata YAML file
        keywords_file_path: Absolute path to the keywords YAML file

    Returns:
        Structured scoring result containing total score, coverage, placement, efficiency, etc.
    """
    import subprocess

    import yaml

    auto_aso_dir = os.environ.get("AUTO_ASO_DIR", "/Volumes/Crucial X9/Code/AutoASO")
    score_script = Path(auto_aso_dir) / "score.py"

    if not score_script.exists():
        return {"success": False, "error": f"AutoASO score script not found at {score_script}"}

    try:
        result = subprocess.run(  # noqa: S603
            [
                sys.executable,
                score_script,
                "--metadata",
                metadata_file_path,
                "--keywords",
                keywords_file_path,
            ],
            capture_output=True,
            text=True,
            check=True,
            cwd=auto_aso_dir,
        )
        parsed = yaml.safe_load(result.stdout)
        return {
            "success": True,
            "score_data": parsed,
            "raw_output": result.stdout,
        }
    except subprocess.CalledProcessError as e:
        return {
            "success": False,
            "error": f"Score script failed with exit code {e.returncode}",
            "stdout": e.stdout,
            "stderr": e.stderr,
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Error running scoring engine: {e!s}",
            "raw_output": result.stdout if "result" in locals() else "",
        }


# =============================================================================
# Entry Point
# =============================================================================


def main(argv: list[str] | None = None) -> None:
    """Run the ASO Keyword MCP server."""
    parser = argparse.ArgumentParser(description="ASO Keyword MCP Server")
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8004)

    args = parser.parse_args(argv)

    if args.transport == "streamable-http":
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")
