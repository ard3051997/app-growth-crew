"""Shared structlog configuration for MCP-GC servers."""

from __future__ import annotations

import logging
import os
import sys

import structlog


def configure_logging(env_var_prefix: str, default_level: str = "INFO") -> None:
    """Configure structlog to write to stderr.

    Args:
        env_var_prefix: Server-specific prefix used to read the log level env var.
            E.g. "REVENUECAT_MCP" reads REVENUECAT_MCP_LOG_LEVEL.
        default_level: Fallback log level string (default: "INFO").
    """
    env_var = f"{env_var_prefix}_LOG_LEVEL"
    log_level_str = os.environ.get(env_var, default_level)
    numeric_level = getattr(logging, log_level_str.upper(), logging.INFO)

    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    )
