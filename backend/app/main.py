"""
HexaAgent — Application Entry Point.

Creates the FastAPI application, registers all Phase 1 collectors
and Phase 2A providers, configures middleware, logging, and lifespan events.
"""

from __future__ import annotations

import logging
from app.api.v1.alerts import router as alerts_router
from app.api.v1.history import router as history_router
from app.api.v1.logs import router as logs_router
from app.api.v1.operations import router as operations_router
from app.api.v1.snapshot import router as snapshot_router
from app.api.v1.system import router as system_router
from app.collectors.cpu import CpuCollector
from app.collectors.gpu import GpuCollector
from app.collectors.memory import MemoryCollector
from app.collectors.storage import StorageCollector
from app.core.config import get_settings
from app.core.history import history_engine
from app.core.operations import queue_manager
from app.core.registry import collector_registry
from app.core.snapshot import snapshot_manager
from app.core.snapshot_pusher import snapshot_pusher
from app.core.operations_poller import operations_poller
from app.core.log_pusher import log_pusher
from app.providers.availability import AvailabilityProvider
from app.providers.backend import BackendProvider
from app.providers.cloudflared import CloudflaredProvider
from app.providers.git_provider import GitProvider
from app.providers.nginx import NginxProvider
from app.providers.postgres import PostgresProvider
from app.providers.redis_provider import RedisProvider
from app.providers.system_provider import SystemProvider
from app.reporter import reporter

import sys
from contextlib import asynccontextmanager
from typing import AsyncIterator
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("hexa_agent")


# ---------------------------------------------------------------------------
# Lifespan — startup / shutdown
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Register collectors/providers on startup; clean up on shutdown."""
    settings = get_settings()
    logger.info("HexaAgent starting on %s:%d", settings.HOST, settings.PORT)
    logger.info("Monitoring HexaBeta at: %s", settings.HEXABETA_PROJECT_ROOT)

    # ---- Phase 1 Collectors (unchanged) ----
    collector_registry.register(CpuCollector())
    collector_registry.register(MemoryCollector())
    collector_registry.register(StorageCollector())
    collector_registry.register(GpuCollector())

    # ---- Phase 2A Providers ----
    collector_registry.register(BackendProvider())
    collector_registry.register(PostgresProvider())
    collector_registry.register(RedisProvider())
    collector_registry.register(NginxProvider())
    collector_registry.register(CloudflaredProvider())
    collector_registry.register(GitProvider())
    collector_registry.register(SystemProvider())
    collector_registry.register(AvailabilityProvider())

    # ---- Phase 3 Provider (Read-Only Consumer) ----
    from app.providers.api_provider import ApiProvider
    collector_registry.register(ApiProvider())

    logger.info(
        "Registered collectors/providers: %s",
        ", ".join(collector_registry.registered),
    )

    # ---- Start background services ----
    try:
        from app.utils.service_checker import update_cloudflared_launchagent
        update_cloudflared_launchagent()
    except Exception as e:
        logger.error("Failed to execute update_cloudflared_launchagent on startup: %s", e)

    snapshot_manager.start()
    snapshot_pusher.start()
    reporter.start()
    queue_manager.start_worker()
    history_engine.start()
    operations_poller.start()
    log_pusher.start()

    yield  # Application runs

    logger.info("HexaAgent shutting down")

    # ---- Graceful shutdown ----
    await snapshot_manager.stop()
    await snapshot_pusher.stop()
    await reporter.stop()
    await queue_manager.stop_worker()
    await history_engine.stop()
    await operations_poller.stop()
    await log_pusher.stop()


# ---------------------------------------------------------------------------
# Application Factory
# ---------------------------------------------------------------------------
app = FastAPI(
    title="HexaAgent",
    description=(
        "Lightweight production telemetry agent for the HexaBeta project. "
        "Exposes live CPU, Memory, Storage, GPU, Infrastructure, Deployment, "
        "Availability, and System metrics via REST API."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

# CORS — allow HexaMonitor (or any authorised consumer) to call these APIs.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten in production once HexaMonitor origin is known
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Phase 3: API Observability is now read-only — no middleware needed.
# HexaAgent reads from HexaBeta Backend's api_observability.db.

# Mount API routers
app.include_router(system_router, prefix="/api/v1")     # Phase 1 (unchanged)
app.include_router(snapshot_router, prefix="/api/v1")    # Phase 2A (new)
app.include_router(operations_router, prefix="/api/v1")  # Phase 2B (new)
app.include_router(logs_router, prefix="/api/v1")        # Phase 2B (new)
app.include_router(alerts_router, prefix="/api/v1")      # Phase 2B (new)
app.include_router(history_router, prefix="/api/v1")     # Phase 2B (new)

