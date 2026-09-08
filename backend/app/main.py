"""
HexaMonitor & HexaAgent — Unified FastAPI Application Entry Point.

Registers all HexaMonitor server endpoints/services AND HexaAgent telemetry collectors/providers.
"""

from __future__ import annotations

import os
import sys
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.core.config import settings
from app.core.snapshot import snapshot_manager
from app.core.snapshot_pusher import snapshot_pusher
from app.reporter import reporter
from app.core.operations import queue_manager
from app.core.history import history_engine
from app.core.operations_poller import operations_poller
from app.core.log_pusher import log_pusher

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("hexamonitor")


# ─── Lifespan Event Handler ───────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # --- 1. Start HexaMonitor Server Scheduler ---
    try:
        from app.services.scheduler_service import start_scheduler, shutdown_scheduler
        start_scheduler()
        logger.info("HexaMonitor scheduler started.")
    except Exception as e:
        logger.warning("Could not start HexaMonitor scheduler: %s", e)

    # --- 2. Register HexaAgent Telemetry Collectors & Providers ---
    try:
        from app.core.registry import collector_registry
        from app.collectors.cpu import CpuCollector
        from app.collectors.gpu import GpuCollector
        from app.collectors.memory import MemoryCollector
        from app.collectors.storage import StorageCollector
        from app.providers.availability import AvailabilityProvider
        from app.providers.backend import BackendProvider
        from app.providers.cloudflared import CloudflaredProvider
        from app.providers.git_provider import GitProvider
        from app.providers.nginx import NginxProvider
        from app.providers.postgres import PostgresProvider
        from app.providers.redis_provider import RedisProvider
        from app.providers.system_provider import SystemProvider
        from app.providers.api_provider import ApiProvider

        # Phase 1 Collectors
        collector_registry.register(CpuCollector())
        collector_registry.register(MemoryCollector())
        collector_registry.register(StorageCollector())
        collector_registry.register(GpuCollector())

        # Phase 2A Providers
        collector_registry.register(BackendProvider())
        collector_registry.register(PostgresProvider())
        collector_registry.register(RedisProvider())
        collector_registry.register(NginxProvider())
        collector_registry.register(CloudflaredProvider())
        collector_registry.register(GitProvider())
        collector_registry.register(SystemProvider())
        collector_registry.register(AvailabilityProvider())
        collector_registry.register(ApiProvider())

        logger.info("Registered collectors/providers: %s", ", ".join(collector_registry.registered))

        # Platform service checks
        try:
            from app.utils.service_checker import update_cloudflared_launchagent
            update_cloudflared_launchagent()
        except Exception as e:
            logger.error("Failed to execute update_cloudflared_launchagent: %s", e)

        # Start HexaAgent Background Engines
        snapshot_manager.start()
        snapshot_pusher.start()
        reporter.start()
        queue_manager.start_worker()
        history_engine.start()

        if settings.ENABLE_OPERATIONS_POLLER:
            operations_poller.start()
        else:
            logger.info("Operations poller disabled by configuration (ENABLE_OPERATIONS_POLLER=false)")

        if settings.ENABLE_LOG_PUSHER:
            log_pusher.start()
        else:
            logger.info("Log pusher disabled by configuration (ENABLE_LOG_PUSHER=false)")

    except Exception as e:
        logger.warning("HexaAgent background engines initialization note: %s", e)

    yield  # Application running

    # --- Shutdown Tasks ---
    try:
        from app.services.scheduler_service import shutdown_scheduler
        shutdown_scheduler()
    except Exception:
        pass

    try:

        await snapshot_manager.stop()
        await snapshot_pusher.stop()
        await reporter.stop()
        await queue_manager.stop_worker()
        await history_engine.stop()

        if settings.ENABLE_OPERATIONS_POLLER:
            await operations_poller.stop()

        if settings.ENABLE_LOG_PUSHER:
            await log_pusher.stop()
    except Exception:
        pass


# ─── FastAPI Application Definition ──────────────────────────────────────────

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="HexaMonitor Core API platform specifically tailored for HexaBeta infrastructure.",
    version="2.0.0",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url=f"{settings.API_V1_STR}/docs",
    redoc_url=f"{settings.API_V1_STR}/redoc",
    lifespan=lifespan,
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|hexamonitor\.spicykheer\.com)(:\d+)?",
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Include Routers ───────────────────────────────────────────────────────────

from app.api.v1 import (
    auth,
    api_checks,
    agent_ingest,
    infrastructure,
    agents,
    dashboard,
    operations,
    snapshot,
    logs,
    system,
    alerts,
    history,
)

# HexaMonitor Routers
app.include_router(auth.router, prefix=f"{settings.API_V1_STR}/auth", tags=["Authentication"])
app.include_router(api_checks.router, prefix=f"{settings.API_V1_STR}/api-checks", tags=["Synthetic Monitoring"])
app.include_router(agent_ingest.router, prefix=f"{settings.API_V1_STR}/agent/ingest", tags=["Agent Ingestion"])
app.include_router(infrastructure.router, prefix=f"{settings.API_V1_STR}", tags=["Infrastructure"])
app.include_router(agents.router, prefix=f"{settings.API_V1_STR}/agents", tags=["Agents Phase 1"])
app.include_router(dashboard.router, prefix=f"{settings.API_V1_STR}/dashboard", tags=["Dashboard"])

# Shared / Integrated Routers
app.include_router(system.router, prefix=f"{settings.API_V1_STR}", tags=["System Metrics"])
app.include_router(snapshot.router, prefix=f"{settings.API_V1_STR}", tags=["Snapshot"])
app.include_router(operations.router, prefix=f"{settings.API_V1_STR}", tags=["Operations"])
app.include_router(logs.router, prefix=f"{settings.API_V1_STR}", tags=["Logs"])
app.include_router(alerts.router, prefix=f"{settings.API_V1_STR}", tags=["Alerts"])
app.include_router(history.router, prefix=f"{settings.API_V1_STR}", tags=["History"])


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


# ─── Serve Frontend Static Files ───────────────────────────────────────────────

frontend_dist_dir = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")
)

assets_dir = os.path.join(frontend_dist_dir, "assets")
if os.path.exists(assets_dir):
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")


@app.get("/{catchall:path}")
async def serve_spa(catchall: str):
    if (
        catchall.startswith("api/")
        or catchall.startswith("docs")
        or catchall.startswith("redoc")
        or catchall.startswith("openapi.json")
    ):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Not Found")

    file_path = os.path.join(frontend_dist_dir, catchall)
    if catchall and os.path.exists(file_path) and os.path.isfile(file_path):
        return FileResponse(file_path)

    index_path = os.path.join(frontend_dist_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)

    return {
        "status": "warning",
        "message": "Frontend build files not found. Please build the frontend by running 'npm run build' inside the frontend directory.",
    }
