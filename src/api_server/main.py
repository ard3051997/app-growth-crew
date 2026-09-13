"""Main entry point for the MCP-GC Interactive Frontend API."""

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from funnel_engine.db import DEFAULT_DB_PATH, init_db

from .auth import ApiSecurityMiddleware
from .routes import actions, apps, experiments, portfolio, system, webhooks

init_db(DEFAULT_DB_PATH)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Run durable outbox recovery for the lifetime of the API process."""
    outbox_worker = asyncio.create_task(webhooks.run_revenuecat_outbox_worker())
    try:
        yield
    finally:
        outbox_worker.cancel()
        with suppress(asyncio.CancelledError):
            await outbox_worker


app = FastAPI(
    title="MCP-GC API",
    description="Thin API wrapper for the autonomous mobile app management system.",
    version="1.0.0",
    lifespan=lifespan,
)

default_origins = "http://localhost:5173,http://127.0.0.1:5173"
cors_origins = [
    origin.strip()
    for origin in os.environ.get("MCP_GC_CORS_ORIGINS", default_origins).split(",")
    if origin.strip() and origin.strip() != "*"
]

# Local frontend origins are allowed by default; operators can add explicit origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Security remains outside CORS so authenticated proxy headers are required even
# for preflight requests when secure mode is enabled.
app.add_middleware(ApiSecurityMiddleware)

# Include routers
app.include_router(portfolio.router, prefix="/api/portfolio", tags=["portfolio"])
app.include_router(apps.router, prefix="/api/apps", tags=["apps"])
app.include_router(experiments.router, prefix="/api/experiments", tags=["experiments"])
app.include_router(actions.router, prefix="/api/actions", tags=["actions"])
app.include_router(system.router, prefix="/api/system", tags=["system"])
app.include_router(webhooks.router, prefix="/api/webhooks", tags=["webhooks"])


@app.get("/api/health")
def health_check() -> dict[str, str]:
    """Simple health check endpoint."""
    return {"status": "ok"}
