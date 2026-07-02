"""
HexaAgent — Application Entry Point.

Creates the FastAPI application, registers all Phase 1 collectors,
and configures middleware, logging, and lifespan events.
"""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.system import router as system_router
from app.collectors.cpu import CpuCollector
from app.collectors.gpu import GpuCollector
from app.collectors.memory import MemoryCollector
from app.collectors.storage import StorageCollector
from app.core.config import get_settings
from app.core.registry import collector_registry
from app.reporter import reporter

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
    """Register collectors on startup; clean up on shutdown."""
    settings = get_settings()
    logger.info("HexaAgent starting on %s:%d", settings.HOST, settings.PORT)
    logger.info("Monitoring HexaBeta at: %s", settings.HEXABETA_PROJECT_ROOT)

    # Register Phase 1 collectors
    collector_registry.register(CpuCollector())
    collector_registry.register(MemoryCollector())
    collector_registry.register(StorageCollector())
    collector_registry.register(GpuCollector())

    logger.info(
        "Registered collectors: %s",
        ", ".join(collector_registry.registered),
    )

    # Start the Reporter background task
    reporter.start()

    yield  # Application runs

    logger.info("HexaAgent shutting down")
    
    # Gracefully shutdown Reporter
    await reporter.stop()


# ---------------------------------------------------------------------------
# Application Factory
# ---------------------------------------------------------------------------
app = FastAPI(
    title="HexaAgent",
    description=(
        "Lightweight production telemetry agent for the HexaBeta project. "
        "Exposes live CPU, Memory, Storage, and GPU metrics via REST API."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow HexaMonitor (or any authorised consumer) to call these APIs.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten in production once HexaMonitor origin is known
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)

# Mount the v1 API router
app.include_router(system_router, prefix="/api/v1")
