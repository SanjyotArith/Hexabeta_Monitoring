"""
HexaAgent — Nginx Provider (Phase 2A).

Monitors the Nginx web server: process status, HTTP/HTTPS status,
config validation. READ ONLY.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.registry import BaseCollector
from app.utils.service_checker import find_process_by_name, get_process_metrics

logger = logging.getLogger("hexa_agent.providers.nginx")


class NginxProvider(BaseCollector):
    """Collect Nginx status and metrics."""

    @property
    def name(self) -> str:
        return "nginx"

    async def collect(self) -> dict[str, Any]:
        settings = get_settings()
        result: dict[str, Any] = {
            "running": False,
            "healthy": False,
            "pid": None,
            "cpu_percent": 0.0,
            "memory_bytes": 0,
            "memory_mb": 0.0,
            "http_status": None,
            "https_status": None,
            "config_valid": None,
            "port": 80,
            "last_checked": datetime.now(timezone.utc).isoformat(),
            "error": None,
        }

        try:
            # Find nginx master process
            proc = find_process_by_name("nginx")
            if proc:
                result["running"] = True
                result["pid"] = proc.pid
                metrics = get_process_metrics(proc.pid)
                result["cpu_percent"] = metrics["cpu_percent"]
                result["memory_bytes"] = metrics["memory_bytes"]
                result["memory_mb"] = metrics["memory_mb"]
            else:
                result["error"] = "Nginx process not found"

            # Run checks concurrently
            http_task = _check_http(settings.NGINX_HTTP)
            https_task = _check_http(settings.NGINX_HTTPS)
            config_task = _check_config()

            http_status, https_status, config_valid = await asyncio.gather(
                http_task, https_task, config_task
            )

            result["http_status"] = http_status
            result["https_status"] = https_status
            result["config_valid"] = config_valid

            # Healthy = running + at least HTTP responding
            result["healthy"] = (
                result["running"]
                and http_status is not None
                and 200 <= (http_status or 0) < 500
            )

        except Exception as e:
            logger.exception("Nginx provider error: %s", e)
            result["error"] = str(e)

        return result


async def _check_http(url: str) -> int | None:
    """Return the HTTP status code, or None on failure."""
    try:
        async with httpx.AsyncClient(
            timeout=5.0, verify=False, follow_redirects=True
        ) as client:
            response = await client.get(url)
            return response.status_code
    except Exception:
        return None


async def _check_config() -> bool | None:
    """
    Run ``nginx -t`` to validate the configuration.

    This is a READ-ONLY check — it does not modify anything.
    Returns True if valid, False if invalid, None if unable to run.
    """
    try:
        process = await asyncio.create_subprocess_exec(
            "nginx", "-t",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=5)
        # nginx -t outputs "syntax is ok" and "test is successful" to stderr
        output = stderr.decode().lower()
        return "successful" in output or "syntax is ok" in output
    except (FileNotFoundError, asyncio.TimeoutError):
        return None
