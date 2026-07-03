"""
HexaAgent — System Provider (Phase 2A).

Collects macOS system-level information: hostname, OS version,
architecture, uptime, load average, disk usage. READ ONLY.
"""

from __future__ import annotations

import logging
import platform
import time
from datetime import datetime, timezone
from typing import Any

import psutil

from app.core.config import get_settings
from app.core.registry import BaseCollector

logger = logging.getLogger("hexa_agent.providers.system")


class SystemProvider(BaseCollector):
    """Collect macOS system-level metrics."""

    @property
    def name(self) -> str:
        return "system"

    async def collect(self) -> dict[str, Any]:
        settings = get_settings()
        result: dict[str, Any] = {
            "hostname": None,
            "os_version": None,
            "architecture": None,
            "uptime_seconds": None,
            "load_average_1m": None,
            "load_average_5m": None,
            "load_average_15m": None,
            "disk_total_bytes": None,
            "disk_used_bytes": None,
            "disk_free_bytes": None,
            "disk_percent": None,
            "last_checked": datetime.now(timezone.utc).isoformat(),
            "error": None,
        }

        try:
            # Hostname
            import socket
            result["hostname"] = socket.gethostname()

            # OS version
            result["os_version"] = platform.platform()

            # Architecture
            result["architecture"] = platform.machine()

            # Uptime
            boot_time = psutil.boot_time()
            result["uptime_seconds"] = round(time.time() - boot_time, 0)

            # Load average (macOS/Linux only)
            try:
                load1, load5, load15 = psutil.getloadavg()
                result["load_average_1m"] = round(load1, 2)
                result["load_average_5m"] = round(load5, 2)
                result["load_average_15m"] = round(load15, 2)
            except (AttributeError, OSError):
                pass

            # Disk usage — for the volume containing the HexaBeta project
            project_root = str(settings.project_root)
            try:
                disk = psutil.disk_usage(project_root)
                result["disk_total_bytes"] = disk.total
                result["disk_used_bytes"] = disk.used
                result["disk_free_bytes"] = disk.free
                result["disk_percent"] = disk.percent
            except (FileNotFoundError, OSError):
                # Fallback to root volume
                try:
                    disk = psutil.disk_usage("/")
                    result["disk_total_bytes"] = disk.total
                    result["disk_used_bytes"] = disk.used
                    result["disk_free_bytes"] = disk.free
                    result["disk_percent"] = disk.percent
                except OSError:
                    pass

        except Exception as e:
            logger.exception("System provider error: %s", e)
            result["error"] = str(e)

        return result
