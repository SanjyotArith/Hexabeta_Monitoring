"""
HexaAgent — PostgreSQL Provider (Phase 2A).

Monitors the PostgreSQL service: process status, connection test,
version, current connections. READ ONLY.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.core.config import get_settings
from app.core.registry import BaseCollector
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
            # Check brew service status
            svc = await check_brew_service(settings.POSTGRES_SERVICE)
            result["running"] = svc["running"]
            result["pid"] = svc.get("pid")

            # Fallback: find postgres process via psutil
            if not result["running"]:
                proc = find_process_by_name("postgres")
                if proc:
                    result["running"] = True
                    result["pid"] = proc.pid

            if not result["running"]:
                result["error"] = "PostgreSQL service not running"
                return result

            # Process metrics
            if result["pid"]:
                metrics = get_process_metrics(result["pid"])
                result["cpu_percent"] = metrics["cpu_percent"]
                result["memory_bytes"] = metrics["memory_bytes"]
                result["memory_mb"] = metrics["memory_mb"]

            # Database connection test
            await _test_connection(settings, result)

        except Exception as e:
            logger.exception("PostgreSQL provider error: %s", e)
            result["error"] = str(e)

        return result


async def _test_connection(settings: Any, result: dict[str, Any]) -> None:
    """
    Test PostgreSQL connectivity and gather metadata.

    Uses asyncpg for a lightweight async connection.
    """
    try:
        import asyncpg
    except ImportError:
        result["error"] = "asyncpg not installed"
        return

    conn: Optional[asyncpg.Connection] = None
    try:
        connect_kwargs: dict[str, Any] = {
            "host": "localhost",
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
