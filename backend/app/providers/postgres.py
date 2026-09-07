"""
HexaAgent — PostgreSQL Provider (Phase 2A + Docker Awareness).

Monitors the PostgreSQL service: process status, connection test,
version, current connections. READ ONLY.

Supports three detection modes (via POSTGRES_MODE):
    - `host`: Host-process check only (Homebrew service / psutil process)
    - `docker`: Docker container check only (skips host processes, sets pid=None)
    - `auto`: Host-process check first; falls back to Docker if host process not found
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.core.config import get_settings
from app.core.registry import BaseCollector
from app.utils.docker import (
    get_container_stats,
    is_docker_available,
    list_containers,
)
from app.utils.service_checker import (
    check_brew_service,
    find_process_by_name,
    get_process_metrics,
)

logger = logging.getLogger("hexa_agent.providers.postgres")


class PostgresProvider(BaseCollector):
    """Collect PostgreSQL status and metrics."""

    @property
    def name(self) -> str:
        return "postgres"

    async def collect(self) -> dict[str, Any]:
        settings = get_settings()
        result: dict[str, Any] = {
            "running": False,
            "healthy": False,
            "pid": None,
            "port": settings.POSTGRES_PORT,
            "cpu_percent": 0.0,
            "memory_bytes": 0,
            "memory_mb": 0.0,
            "version": None,
            "connection_test": False,
            "current_connections": None,
            "last_checked": datetime.now(timezone.utc).isoformat(),
            "error": None,
        }

        try:
            postgres_mode = getattr(settings, "POSTGRES_MODE", "auto").lower()
            docker_enabled = getattr(settings, "DOCKER_ENABLED", True)

            # 1. Host Mode: process detection only
            if postgres_mode == "host":
                await self._check_host_process(settings, result)

            # 2. Docker Mode: container detection only (skips host process search)
            elif postgres_mode == "docker":
                if docker_enabled:
                    await self._check_docker_container(settings, result)
                else:
                    result["error"] = "Docker detection disabled in configuration (DOCKER_ENABLED=false)"

            # 3. Auto Mode: host process first, fallback to Docker
            else:
                await self._check_host_process(settings, result)
                if not result["running"] and docker_enabled:
                    await self._check_docker_container(settings, result)

            if not result["running"]:
                if not result.get("error"):
                    result["error"] = "PostgreSQL service or container not running"
                return result

            # Database Connection Test (runs in all modes when postgres is running)
            await _test_connection(settings, result)

        except Exception as e:
            logger.exception("PostgreSQL provider error: %s", e)
            result["error"] = str(e)

        return result

    async def _check_host_process(self, settings: Any, result: dict[str, Any]) -> None:
        """Check host Homebrew service or psutil process for postgres."""
        svc = await check_brew_service(settings.POSTGRES_SERVICE)
        if svc["running"]:
            result["running"] = True
            result["pid"] = svc.get("pid")
        else:
            proc = find_process_by_name("postgres")
            if proc:
                result["running"] = True
                result["pid"] = proc.pid

        if result["running"] and result["pid"]:
            metrics = get_process_metrics(result["pid"])
            result["cpu_percent"] = metrics["cpu_percent"]
            result["memory_bytes"] = metrics["memory_bytes"]
            result["memory_mb"] = metrics["memory_mb"]

    async def _check_docker_container(self, settings: Any, result: dict[str, Any]) -> None:
        """Check Docker containers for postgres matching POSTGRES_CONTAINER_PATTERNS."""
        docker_status = await is_docker_available()
        if not docker_status.available:
            if not result.get("error"):
                result["error"] = f"Docker not available: {docker_status.error}"
            return

        patterns = settings.postgres_container_patterns
        containers, err = await list_containers(
            patterns,
            timeout=settings.DOCKER_COMMAND_TIMEOUT,
        )
        if err:
            result["error"] = err
            return

        if containers:
            running_containers = [
                c for c in containers
                if c.get("State") == "running" or "Up" in c.get("Status", "")
            ]
            target_container = running_containers[0] if running_containers else containers[0]

            result["running"] = True
            result["pid"] = None  # No host PID in Docker mode

            cid = target_container.get("ID", "")
            if cid:
                stats, stats_err = await get_container_stats(
                    cid,
                    timeout=settings.DOCKER_COMMAND_TIMEOUT,
                )
                if stats:
                    result["cpu_percent"] = stats.get("cpu_percent", 0.0)
                    mem_bytes = stats.get("memory_bytes", 0)
                    result["memory_bytes"] = mem_bytes
                    result["memory_mb"] = round(mem_bytes / (1024 * 1024), 2)


async def _test_connection(settings: Any, result: dict[str, Any]) -> None:
    """
    Test PostgreSQL connectivity and gather metadata.

    Uses asyncpg for a lightweight async connection.
    Connects using configured POSTGRES_HOST, POSTGRES_PORT, POSTGRES_USER, etc.
    """
    try:
        import asyncpg
    except ImportError:
        result["error"] = "asyncpg not installed"
        return

    conn: Optional[asyncpg.Connection] = None
    try:
        connect_kwargs: dict[str, Any] = {
            "host": settings.POSTGRES_HOST,
            "port": settings.POSTGRES_PORT,
            "user": settings.POSTGRES_USER,
            "database": settings.POSTGRES_DATABASE,
            "timeout": 5,
        }
        if settings.POSTGRES_PASSWORD:
            connect_kwargs["password"] = settings.POSTGRES_PASSWORD

        conn = await asyncpg.connect(**connect_kwargs)

        # Connection test — SELECT NOW()
        await conn.fetchval("SELECT NOW()")
        result["connection_test"] = True

        # Version
        version = await conn.fetchval("SHOW server_version")
        result["version"] = version

        # Current connections
        conn_count = await conn.fetchval(
            "SELECT count(*) FROM pg_stat_activity"
        )
        result["current_connections"] = conn_count

        result["healthy"] = True

    except Exception as e:
        logger.warning("PostgreSQL connection test failed: %s", e)
        result["connection_test"] = False
        result["error"] = f"Connection failed: {e}"

    finally:
        if conn:
            await conn.close()
