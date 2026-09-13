"""Authentication and request authorization for the managed API."""

from __future__ import annotations

import hashlib
import os
import secrets
from typing import TYPE_CHECKING

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
REVENUECAT_WEBHOOK_PATH = "/api/webhooks/revenuecat"


def env_enabled(name: str) -> bool:
    """Return whether an opt-in environment flag is enabled."""
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def config_writes_enabled() -> bool:
    """Return whether local configuration mutation is explicitly available."""
    return env_enabled("MCP_GC_CONFIG_WRITES_ENABLED") and not env_enabled("MCP_GC_READ_ONLY")


def _secret_matches(candidate: str, expected: str | None) -> bool:
    """Compare secret digests so comparison time does not expose secret length."""
    candidate_digest = hashlib.sha256(candidate.encode()).digest()
    expected_digest = hashlib.sha256((expected or "").encode()).digest()
    return expected is not None and secrets.compare_digest(candidate_digest, expected_digest)


def revenuecat_webhook_is_verified(request: Request) -> bool:
    """Verify the provider-configured RevenueCat shared-secret header."""
    expected = os.environ.get("MCP_GC_REVENUECAT_WEBHOOK_SECRET")
    header_name = os.environ.get("MCP_GC_REVENUECAT_WEBHOOK_HEADER", "Authorization").strip()
    if not expected or not header_name:
        return False
    return _secret_matches(request.headers.get(header_name, ""), expected)


def revenuecat_verification_required() -> bool:
    """Require provider verification except for an explicit local-development bypass."""
    environment = os.environ.get("MCP_GC_ENV", "local").strip().lower()
    local_development = environment in {"local", "dev", "development", "test"}
    return not (local_development and env_enabled("MCP_GC_INSECURE_DEV_WEBHOOKS"))


def _request_identity(request: Request) -> tuple[str, str] | None:
    authorization = request.headers.get("Authorization", "")
    scheme, separator, credential = authorization.partition(" ")
    if separator and scheme.lower() == "bearer" and credential:
        admin_match = _secret_matches(credential, os.environ.get("MCP_GC_ADMIN_API_KEY"))
        viewer_match = _secret_matches(credential, os.environ.get("MCP_GC_VIEWER_API_KEY"))
        if admin_match:
            return "admin", "api-key:admin"
        if viewer_match:
            return "viewer", "api-key:viewer"

    proxy_token = request.headers.get("X-MCP-GC-Proxy-Token", "")
    if _secret_matches(proxy_token, os.environ.get("MCP_GC_PROXY_SHARED_TOKEN")):
        proxy_role = request.headers.get("X-MCP-GC-Proxy-Role", "").strip().lower()
        if proxy_role in {"admin", "viewer"}:
            return proxy_role, f"proxy:{proxy_role}"
    return None


def authenticated_actor(request: Request) -> str:
    """Return the middleware-derived actor for an attributable semantic action."""
    actor = getattr(request.state, "auth_actor", None)
    if actor:
        return str(actor)
    raise RuntimeError("Authenticated actor is unavailable")


def _error(status_code: int, detail: str, *, bearer_challenge: bool = False) -> JSONResponse:
    headers = {"WWW-Authenticate": "Bearer"} if bearer_challenge else None
    return JSONResponse({"detail": detail}, status_code=status_code, headers=headers)


class ApiSecurityMiddleware(BaseHTTPMiddleware):
    """Enforce API authentication, roles, and the global read-only switch."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        path = request.url.path
        if path != "/api" and not path.startswith("/api/"):
            return await call_next(request)
        if path == "/api/health":
            return await call_next(request)

        verified_webhook = path == REVENUECAT_WEBHOOK_PATH and revenuecat_webhook_is_verified(
            request
        )
        request.state.revenuecat_webhook_verified = verified_webhook

        if (
            path == REVENUECAT_WEBHOOK_PATH
            and revenuecat_verification_required()
            and not verified_webhook
        ):
            return _error(401, "Invalid RevenueCat webhook secret")

        identity = _request_identity(request)
        request.state.auth_role = identity[0] if identity else None
        request.state.auth_actor = (
            identity[1]
            if identity
            else "local:developer"
            if not env_enabled("MCP_GC_API_AUTH_REQUIRED")
            else None
        )

        if env_enabled("MCP_GC_API_AUTH_REQUIRED") and not verified_webhook:
            role = identity[0] if identity else None
            if role is None:
                return _error(401, "Authentication required", bearer_challenge=True)
            if request.method not in SAFE_METHODS and role != "admin":
                return _error(403, "Admin role required")

        if env_enabled("MCP_GC_READ_ONLY") and request.method not in SAFE_METHODS:
            return _error(403, "API is in read-only mode; webhook processing is disabled")

        return await call_next(request)
