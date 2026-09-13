"""Shared .env loader for MCP-GC servers."""

from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path


def load_dotenv() -> None:
    """Load .env from the project root (walks up to 5 parent dirs).

    Skips loading when running under pytest to avoid polluting test env.
    Warns (instead of silently swallowing) on parse errors.
    Only sets keys not already present in the process environment.
    """
    if "pytest" in sys.modules:
        return

    dotenv_path = Path(".env")
    if not dotenv_path.exists():
        curr = Path(__file__).resolve()
        for _ in range(5):
            curr = curr.parent
            candidate = curr / ".env"
            if candidate.exists():
                dotenv_path = candidate
                break

    if not dotenv_path.exists():
        return

    try:
        with dotenv_path.open() as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    if key and key not in os.environ:
                        os.environ[key] = val
    except OSError as exc:
        warnings.warn(f"Could not read .env file at {dotenv_path}: {exc}", stacklevel=2)
