"""Google Cloud Storage MCP Server."""

import sys

from .server import mcp


def main() -> int:
    """Run the GCS MCP server."""
    mcp.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
