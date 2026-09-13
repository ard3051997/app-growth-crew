"""Image Generation MCP Server — generates creative assets via Gemini image models."""

import sys

from image_gen_mcp.server import mcp


def main() -> int:
    """Run the Image Generation MCP server."""
    mcp.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())

__all__ = ["main", "mcp"]
