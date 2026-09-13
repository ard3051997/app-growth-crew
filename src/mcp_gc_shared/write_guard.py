"""Process-wide guard for operations that mutate external systems."""

from __future__ import annotations

import os


class WriteBlockedError(RuntimeError):
    """Raised when an external mutation is attempted in read-only mode."""


def env_flag(name: str) -> bool:
    """Return whether an opt-in environment flag is enabled."""
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def is_read_only() -> bool:
    """Return the process-wide read-only state."""
    return env_flag("MCP_GC_READ_ONLY")


def assert_writes_allowed(operation: str = "External write") -> None:
    """Reject an external mutation when the process is configured read-only."""
    if is_read_only():
        raise WriteBlockedError(f"{operation} is blocked by MCP_GC_READ_ONLY")
