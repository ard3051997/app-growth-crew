"""Journey Map MCP Server — generates interactive journey_map.html."""

import sys

from journey_map_mcp.server import mcp


def main() -> int:
    """Run the Journey Map MCP server."""
    mcp.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())

__all__ = ["main", "mcp"]
