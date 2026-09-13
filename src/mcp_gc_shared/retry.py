"""Shared retry-with-backoff decorator factory for MCP-GC clients."""

from __future__ import annotations

import functools
import random
import time
from collections.abc import Callable
from typing import TypeVar

import structlog

# Shared defaults — clients can override by passing kwargs to retry_on_transient().
MAX_RETRIES: int = 3
INITIAL_BACKOFF: float = 1.0
MAX_BACKOFF: float = 32.0

_logger = structlog.get_logger(__name__)

F = TypeVar("F", bound=Callable)


def retry_on_transient(
    *transient_exception_types: type[BaseException],
    max_retries: int = MAX_RETRIES,
    initial_backoff: float = INITIAL_BACKOFF,
    max_backoff: float = MAX_BACKOFF,
) -> Callable[[F], F]:
    """Decorator factory that retries a function on any of the listed exception types.

    Usage::

        from mcp_gc_shared.retry import retry_on_transient
        from google.api_core.exceptions import TooManyRequests, ServiceUnavailable

        @retry_on_transient(TooManyRequests, ServiceUnavailable)
        def my_api_call(): ...

    For exception types that require status-code filtering (e.g. ``HttpError``),
    keep a custom decorator in the client module instead of using this factory.
    """
    if not transient_exception_types:
        raise ValueError("retry_on_transient requires at least one exception type")

    exc_tuple = tuple(transient_exception_types)

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):  # type: ignore[no-untyped-def]
            retries = 0
            backoff = initial_backoff
            while retries < max_retries:
                try:
                    return func(*args, **kwargs)
                except exc_tuple as e:
                    retries += 1
                    if retries >= max_retries:
                        raise
                    sleep_time = backoff * (0.5 + random.random())  # noqa: S311
                    _logger.warning(
                        "transient error, retrying",
                        error=type(e).__name__,
                        retry=retries,
                        sleep=round(sleep_time, 2),
                    )
                    time.sleep(sleep_time)
                    backoff = min(backoff * 2, max_backoff)

        return wrapper  # type: ignore[return-value]

    return decorator
