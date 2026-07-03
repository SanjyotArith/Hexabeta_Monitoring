"""
HexaAgent — Redis Provider (Phase 2A).

Monitors the Redis service: process status, PING, version,
memory usage. READ ONLY.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.core.config import get_settings
from app.core.registry import BaseCollector
from app.utils.service_checker import find_process_by_name, get_process_metrics

logger = logging.getLogger("hexa_agent.providers.redis")


class RedisProvider(BaseCollector):
    """Collect Redis status and metrics."""

    @property
    def name(self) -> str:
        return "redis"

    async def collect(self) -> dict[str, Any]:
        settings = get_settings()
        result: dict[str, Any] = {
            "running": False,
            "healthy": False,
            "pid": None,
            "port": settings.REDIS_PORT,
            "cpu_percent": 0.0,
            "memory_bytes": 0,
            "memory_mb": 0.0,
            "version": None,
            "ping": False,
            "memory_used_bytes": None,
            "last_checked": datetime.now(timezone.utc).isoformat(),
            "error": None,
        }

        try:
            # Find redis process
            proc = find_process_by_name("redis-server")
            if proc:
                result["running"] = True
                result["pid"] = proc.pid
                metrics = get_process_metrics(proc.pid)
                result["cpu_percent"] = metrics["cpu_percent"]
                result["memory_bytes"] = metrics["memory_bytes"]
                result["memory_mb"] = metrics["memory_mb"]

            # Test Redis connectivity
            await _test_redis(settings, result)

            if not result["running"] and not result["ping"]:
                result["error"] = "Redis not running"

        except Exception as e:
            logger.exception("Redis provider error: %s", e)
            result["error"] = str(e)

        return result


async def _test_redis(settings: Any, result: dict[str, Any]) -> None:
    """Test Redis connectivity using redis-py async client."""
    try:
        import redis.asyncio as aioredis
    except ImportError:
        result["error"] = "redis package not installed"
        return

    client = None
    try:
        client = aioredis.Redis(
            host="localhost",
            port=settings.REDIS_PORT,
            socket_timeout=5,
            socket_connect_timeout=5,
        )

        # PING
        pong = await client.ping()
        result["ping"] = bool(pong)
        result["running"] = True

        # Server info — version
        info_server = await client.info("server")
        result["version"] = info_server.get("redis_version")

        # Memory info
        info_memory = await client.info("memory")
        used = info_memory.get("used_memory")
        if used is not None:
            result["memory_used_bytes"] = int(used)

        result["healthy"] = True

    except Exception as e:
        logger.warning("Redis connection test failed: %s", e)
        result["ping"] = False
        if not result.get("error"):
            result["error"] = f"Connection failed: {e}"

    finally:
        if client:
            await client.aclose()
