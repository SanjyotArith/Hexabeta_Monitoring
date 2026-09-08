"""
HexaAgent — Backend Provider (Phase 2A + Docker Awareness).

Monitors the HexaBeta FastAPI backend: process status, health checks,
resource usage, and version. READ ONLY — never restarts anything.

Supports three detection modes:
    - ``host``  : Existing host-process detection only.
    - ``docker``: Docker container detection only.
    - ``auto``  : Try host first, fall back to Docker if available.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

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
            "detection_mode": None,
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
            "containers": None,
        }

        try:
            mode = settings.BACKEND_MODE.lower().strip()

            if mode == "host":
                await self._collect_host(settings, result)
            elif mode == "docker":
                await self._collect_docker(settings, result)
            elif mode == "auto":
                await self._collect_auto(settings, result)
            else:
                logger.warning(
                    "Unknown BACKEND_MODE '%s' — falling back to 'auto'", mode
                )
                await self._collect_auto(settings, result)

        except Exception as e:
            logger.exception("Backend provider error: %s", e)
            result["error"] = str(e)

        return result

    # ------------------------------------------------------------------
    # Auto Mode
    # ------------------------------------------------------------------

    async def _collect_auto(
        self, settings: Any, result: dict[str, Any]
    ) -> None:
        """Try host-process detection first; fall back to Docker."""
        # Step 1: Try host processes
        host_found = await self._try_host(settings, result)
        if host_found:
            return

        # Step 2: Try Docker if enabled
        if settings.DOCKER_ENABLED:
            docker_found = await self._try_docker(settings, result)
            if docker_found:
                return

        # Step 3: Neither found
        result["error"] = "HexaBeta backend not found (host process or Docker)"

    # ------------------------------------------------------------------
    # Host-Process Mode (existing behavior, unchanged)
    # ------------------------------------------------------------------

    async def _collect_host(
        self, settings: Any, result: dict[str, Any]
    ) -> None:
        """Collect using host-process detection only."""
        found = await self._try_host(settings, result)
        if not found:
            result["error"] = "HexaBeta backend process not found"

    async def _try_host(
        self, settings: Any, result: dict[str, Any]
    ) -> bool:
        """
        Attempt host-process detection.

        Returns True if processes were found and metrics collected.
        """
        import psutil

        processes = find_hexabeta_processes(settings)
        if not processes:
            return False

        result["detection_mode"] = "host"
        result["running"] = True
        main_proc = processes[0]
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

        # Health checks
        await self._run_health_checks(settings, result)

        logger.debug("Backend detection mode: host (PID %d)", main_proc.pid)
        return True

    # ------------------------------------------------------------------
    # Docker Mode
    # ------------------------------------------------------------------

    async def _collect_docker(
        self, settings: Any, result: dict[str, Any]
    ) -> None:
        """Collect using Docker container detection only."""
        if not settings.DOCKER_ENABLED:
            result["error"] = "Docker detection disabled (DOCKER_ENABLED=false)"
            return

        found = await self._try_docker(settings, result)
        if not found:
            result["error"] = "No matching HexaBeta backend containers found"

    async def _try_docker(
        self, settings: Any, result: dict[str, Any]
    ) -> bool:
        """
        Attempt Docker container detection.

        Returns True if containers were found and metrics collected.
        """
        from app.utils.docker import (
            is_docker_available,
            list_containers,
            get_container_stats,
            inspect_container,
            extract_health_from_inspect,
            extract_started_at,
        )

        # Check Docker availability
        docker_status = await is_docker_available()
        if not docker_status.available:
            logger.debug("Docker not available: %s", docker_status.error)
            return False

        # Find matching containers
        patterns = settings.backend_container_patterns
        if not patterns:
            logger.debug("No backend container patterns configured")
            return False

        containers, err = await list_containers(
            patterns, timeout=settings.DOCKER_COMMAND_TIMEOUT
        )
        if err:
            logger.warning("Error listing Docker containers: %s", err)
            return False

        if not containers:
            logger.debug("No matching backend containers found")
            return False

        # Collect metrics from each container
        container_details: list[dict[str, Any]] = []
        total_cpu = 0.0
        total_mem = 0
        detected_names: list[str] = []

        for container in containers:
            cid = container.get("ID", "")
            cname = container.get("Name", "")
            detected_names.append(cname)

            detail: dict[str, Any] = {
                "id": cid[:12] if len(cid) > 12 else cid,
                "name": cname,
                "image": container.get("Image", ""),
                "status": container.get("Status", ""),
                "state": container.get("State", ""),
                "health": None,
                "cpu_percent": 0.0,
                "memory_bytes": 0,
                "memory_mb": 0.0,
                "memory_limit_bytes": None,
                "uptime_seconds": None,
                "ports": container.get("Ports", ""),
                "created": container.get("CreatedAt", ""),
            }

            # Get CPU/Memory stats
            stats, stats_err = await get_container_stats(
                cid, timeout=settings.DOCKER_COMMAND_TIMEOUT
            )
            if stats and not stats_err:
                detail["cpu_percent"] = round(stats.get("cpu_percent", 0.0), 2)
                detail["memory_bytes"] = stats.get("memory_bytes", 0)
                detail["memory_mb"] = round(
                    stats.get("memory_bytes", 0) / (1024 * 1024), 2
                )
                detail["memory_limit_bytes"] = stats.get("memory_limit_bytes")
                total_cpu += detail["cpu_percent"]
                total_mem += detail["memory_bytes"]
            elif stats_err:
                logger.debug(
                    "Could not get stats for container %s: %s", cname, stats_err
                )

            # Get health + uptime from inspect
            inspection, inspect_err = await inspect_container(
                cid, timeout=settings.DOCKER_COMMAND_TIMEOUT
            )
            if inspection and not inspect_err:
                detail["health"] = extract_health_from_inspect(inspection)
                started_at = extract_started_at(inspection)
                if started_at:
                    detail["uptime_seconds"] = _parse_uptime(started_at)
            elif inspect_err:
                logger.debug(
                    "Could not inspect container %s: %s", cname, inspect_err
                )

            container_details.append(detail)

        # Populate result
        result["detection_mode"] = "docker"
        result["running"] = True
        result["pid"] = None  # No host PID in Docker mode
        result["cpu_percent"] = round(total_cpu, 2)
        result["memory_bytes"] = total_mem
        result["memory_mb"] = round(total_mem / (1024 * 1024), 2) if total_mem > 0 else 0.0
        result["containers"] = container_details

        # Use uptime from the first container (primary instance)
        if container_details and container_details[0].get("uptime_seconds") is not None:
            result["uptime_seconds"] = container_details[0]["uptime_seconds"]

        # Health checks (using configurable URLs — not container addresses)
        await self._run_health_checks(settings, result)

        logger.info(
            "Backend detection mode: docker — containers: %s",
            ", ".join(detected_names),
        )
        return True

    # ------------------------------------------------------------------
    # Shared: Health Checks
    # ------------------------------------------------------------------

    async def _run_health_checks(
        self, settings: Any, result: dict[str, Any]
    ) -> None:
        """Run internal and external health checks and determine overall health."""
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


# ======================================================================
# Module-Level Helpers
# ======================================================================

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


def _parse_uptime(started_at: str) -> Optional[float]:
    """
    Parse a Docker StartedAt ISO timestamp and return seconds since then.

    Returns None if parsing fails.
    """
    if not started_at or started_at == "0001-01-01T00:00:00Z":
        return None

    try:
        # Docker timestamps: "2026-09-07T10:00:00.123456789Z"
        # Python's fromisoformat can't handle nanoseconds, so truncate
        cleaned = started_at
        if "." in cleaned:
            # Keep up to 6 decimal places (microseconds)
            dot_idx = cleaned.index(".")
            # Find the end (Z or +/-)
            for end_char in ("Z", "+", "-"):
                end_idx = cleaned.find(end_char, dot_idx + 1)
                if end_idx > 0:
                    frac = cleaned[dot_idx + 1 : end_idx][:6]
                    cleaned = cleaned[:dot_idx + 1] + frac + cleaned[end_idx:]
                    break

        # Replace trailing Z with +00:00 for fromisoformat
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1] + "+00:00"

        started = datetime.fromisoformat(cleaned)
        now = datetime.now(timezone.utc)
        delta = (now - started).total_seconds()
        return round(delta, 0) if delta > 0 else 0.0

    except (ValueError, TypeError):
        return None
