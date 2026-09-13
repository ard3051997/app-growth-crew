"""Entry point for the funnel engine MCP server."""

import structlog

from funnel_engine_mcp.server import mcp


def main() -> None:
    """Run the Funnel Engine MCP server."""
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
    )
    mcp.run()


if __name__ == "__main__":
    main()
