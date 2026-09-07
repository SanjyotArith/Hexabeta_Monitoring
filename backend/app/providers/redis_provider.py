"""
HexaAgent — Redis Provider (Phase 2A + Docker Awareness).

Monitors the Redis service: process status, PING, version,
memory usage. READ ONLY.

Supports both host mode (macOS process detection) and Docker container mode
(GCP VM container detection using network IP from docker inspect).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.core.config import get_settings
from app.core.registry import BaseCollector
from app.utils.docker import (
    get_container_stats,
    inspect_container,
    is_docker_available,
    list_containers,
)
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
            detection_mode = getattr(settings, "BACKEND_MODE", "auto").lower()
            docker_enabled = getattr(settings, "DOCKER_ENABLED", True)

            target_host: Optional[str] = None
            target_port: int = settings.REDIS_PORT
            is_docker_mode: bool = False

            # 1. Host Mode Check (unless explicitly set to docker mode)
            if detection_mode != "docker":
                proc = find_process_by_name("redis-server")
                if proc:
                    result["running"] = True
                    result["pid"] = proc.pid
                    metrics = get_process_metrics(proc.pid)
                    result["cpu_percent"] = metrics["cpu_percent"]
                    result["memory_bytes"] = metrics["memory_bytes"]
                    result["memory_mb"] = metrics["memory_mb"]
                    target_host = settings.REDIS_HOST
                    target_port = settings.REDIS_PORT

            # 2. Docker Container Fallback (if host process not found or mode == docker)
            if not result["running"] and docker_enabled and detection_mode != "host":
                docker_status = await is_docker_available()
                if docker_status.available:
                    patterns = settings.redis_container_patterns
                    containers, err = await list_containers(
                        patterns,
                        timeout=settings.DOCKER_COMMAND_TIMEOUT,
                    )
                    if containers:
                        running_containers = [
                            c for c in containers
                            if c.get("State") == "running" or "Up" in c.get("Status", "")
                        ]
                        target_container = running_containers[0] if running_containers else containers[0]

                        result["running"] = True
                        result["pid"] = None  # No host PID in Docker mode
                        is_docker_mode = True

                        cid = target_container.get("ID", "")
                        if cid:
                            # Fetch stats for CPU/memory
                            stats, stats_err = await get_container_stats(
                                cid,
                                timeout=settings.DOCKER_COMMAND_TIMEOUT,
                            )
                            if stats:
                                result["cpu_percent"] = stats.get("cpu_percent", 0.0)
                                mem_bytes = stats.get("memory_bytes", 0)
                                result["memory_bytes"] = mem_bytes
                                result["memory_mb"] = round(mem_bytes / (1024 * 1024), 2)

                            # Inspect container to dynamically extract IP address
                            inspection, inspect_err = await inspect_container(
                                cid,
                                timeout=settings.DOCKER_COMMAND_TIMEOUT,
                            )
                            target_host = _get_container_ip(inspection)
                            target_port = 6379  # Container internal port

            # 3. Test Redis connectivity
            if target_host is not None:
                await _test_redis(settings, result, target_host=target_host, target_port=target_port, is_docker_mode=is_docker_mode)
            elif is_docker_mode and target_host is None:
                result["ping"] = False
                result["healthy"] = False
                result["error"] = "Redis container found but no IP address available on Docker network"
            elif not result["running"] and not result["ping"]:
                # Try default host connection if nothing detected yet
                await _test_redis(settings, result, target_host=settings.REDIS_HOST, target_port=settings.REDIS_PORT, is_docker_mode=False)

            if not result["running"] and not result["ping"]:
                if not result.get("error"):
                    result["error"] = "Redis service or container not running"

        except Exception as e:
            logger.exception("Redis provider error: %s", e)
            result["error"] = str(e)

        return result


def _get_container_ip(inspection: Optional[dict[str, Any]]) -> Optional[str]:
    """
    Extract container IP from docker inspect dict.
    Checks NetworkSettings.IPAddress and NetworkSettings.Networks.<name>.IPAddress.
    """
    if not inspection or not isinstance(inspection, dict):
        return None
    net_settings = inspection.get("NetworkSettings", {})
    if not net_settings:
        return None
    ip = net_settings.get("IPAddress")
    if ip:
        return ip
    networks = net_settings.get("Networks", {})
    for net_info in networks.values():
        if isinstance(net_info, dict) and net_info.get("IPAddress"):
            return net_info["IPAddress"]
    return None


async def _test_redis(
    settings: Any,
    result: dict[str, Any],
    target_host: str,
    target_port: int,
    is_docker_mode: bool = False,
) -> None:
    """Test Redis connectivity using redis-py async client."""
    try:
        import redis.asyncio as aioredis
    except ImportError:
        result["error"] = "redis package not installed"
        return

    client = None
    try:
        client = aioredis.Redis(
            host=target_host,
            port=target_port,
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
        logger.warning("Redis connection test failed (%s:%s): %s", target_host, target_port, e)
        result["ping"] = False
        result["healthy"] = False
        if is_docker_mode:
            result["error"] = f"Redis Docker connection failed to {target_host}:{target_port}: {e}"
        elif not result.get("error"):
            result["error"] = f"Connection failed: {e}"

    finally:
        if client:
            await client.aclose()
