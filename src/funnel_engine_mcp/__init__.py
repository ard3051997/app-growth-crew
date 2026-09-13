"""Funnel Engine MCP Server.

Provides tools for full funnel stitching, leak detection, and benchmarking
using the Funnel Analysis Engine.
"""

import sys

from funnel_engine_mcp.server import mcp


def main() -> int:
    """Run the Funnel Engine MCP server."""
    mcp.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())

__all__ = ["main", "mcp"]
