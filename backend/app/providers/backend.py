"""
HexaAgent — Backend Provider (Phase 2A).

Monitors the HexaBeta FastAPI backend: process status, health checks,
resource usage, and version. READ ONLY — never restarts anything.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
import psutil

from app.core.config import get_settings
from app.core.registry import BaseCollector
from app.utils.process_finder import find_hexabeta_processes
from app.utils.service_checker import get_process_metrics

logger = logging.getLogger("hexa_agent.providers.backend")


class BackendProvider(BaseCollector):
    """Collect HexaBeta backend status, health, and resource usage."""

    @property
    def name(self) -> str:
        return "backend"

    async def collect(self) -> dict[str, Any]:
        settings = get_settings()
        result: dict[str, Any] = {
            "running": False,
            "healthy": False,
            "pid": None,
            "port": settings.HEXABETA_BACKEND_PORT,
            "cpu_percent": 0.0,
            "memory_bytes": 0,
            "memory_mb": 0.0,
            "uptime_seconds": None,
            "version": None,
            "internal_health": None,
            "external_health": None,
            "last_checked": datetime.now(timezone.utc).isoformat(),
            "error": None,
        }

        try:
            # Find the backend process
            processes = find_hexabeta_processes(settings)
            if not processes:
                result["error"] = "HexaBeta backend process not found"
                return result

            main_proc = processes[0]
            result["running"] = True
            result["pid"] = main_proc.pid

            # Process metrics (aggregate across main + workers)
            total_cpu = 0.0
            total_mem = 0
            for proc in processes:
                metrics = get_process_metrics(proc.pid)
                total_cpu += metrics["cpu_percent"]
                total_mem += metrics["memory_bytes"]

            result["cpu_percent"] = round(total_cpu, 2)
            result["memory_bytes"] = total_mem
            result["memory_mb"] = round(total_mem / (1024 * 1024), 2)

            # Uptime
            try:
                create_time = main_proc.create_time()
                result["uptime_seconds"] = round(time.time() - create_time, 0)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

            # Internal health check
            result["internal_health"] = await _check_health(
                settings.BACKEND_INTERNAL_HEALTH_URL
            )

            # External health check
            result["external_health"] = await _check_health(
                settings.BACKEND_EXTERNAL_HEALTH_URL
            )

            # Version from health endpoint response
            if result["internal_health"] and result["internal_health"].get("healthy"):
                result["version"] = result["internal_health"].get("version")

            # Overall healthy = running + internal health OK
            result["healthy"] = (
                result["running"]
                and result["internal_health"] is not None
                and result["internal_health"].get("healthy", False)
            )

        except Exception as e:
            logger.exception("Backend provider error: %s", e)
            result["error"] = str(e)

        return result


async def _check_health(url: str) -> dict[str, Any]:
    """
    Perform a GET request to the health endpoint and measure response time.

    Returns
    -------
    dict
        ``{"healthy": bool, "http_status": int | None,
           "response_time_ms": float, "version": str | None, "error": str | None}``
    """
    health: dict[str, Any] = {
        "healthy": False,
        "http_status": None,
        "response_time_ms": 0.0,
        "version": None,
        "error": None,
    }

    try:
        async with httpx.AsyncClient(timeout=5.0, verify=False) as client:
            start = time.monotonic()
            response = await client.get(url)
            elapsed = (time.monotonic() - start) * 1000

            health["http_status"] = response.status_code
            health["response_time_ms"] = round(elapsed, 2)
            health["healthy"] = 200 <= response.status_code < 300

            # Try to extract version from response body
            try:
                body = response.json()
                if isinstance(body, dict):
                    health["version"] = body.get("version") or body.get("app_version")
            except Exception:
                pass

    except httpx.TimeoutException:
        health["error"] = "Timeout"
    except httpx.ConnectError:
        health["error"] = "Connection refused"
    except Exception as e:
        health["error"] = str(e)

    return health
