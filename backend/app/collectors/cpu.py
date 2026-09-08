"""
HexaAgent — CPU Collector.

Aggregates CPU usage across all HexaBeta backend processes
(host uvicorn processes or Docker containers).
"""

from __future__ import annotations

import logging
from typing import Any

import psutil

from app.core.config import get_settings
from app.core.registry import BaseCollector
from app.utils.process_finder import find_hexabeta_processes
from app.utils.docker import is_docker_available, list_containers, get_container_stats

logger = logging.getLogger("hexa_agent.collectors.cpu")


class CpuCollector(BaseCollector):
    """Collect aggregated CPU percent for the HexaBeta backend."""

    @property
    def name(self) -> str:
        return "cpu"

    async def collect(self) -> dict[str, Any]:
        """
        Return the combined CPU usage of all HexaBeta backend processes or containers.

        Returns
        -------
        dict
            ``{"cpu_percent": <float>}``
        """
        settings = get_settings()

        # Step 1: Try host processes
        processes = find_hexabeta_processes(settings)
        if processes:
            total_cpu: float = 0.0
            for proc in processes:
                try:
                    total_cpu += proc.cpu_percent(interval=None)
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue

            total_cpu = round(total_cpu, 2)
            logger.debug("HexaBeta CPU (host): %.2f%%", total_cpu)
            return {"cpu_percent": total_cpu}

        # Step 2: Try Docker containers if enabled
        if settings.DOCKER_ENABLED:
            docker_status = await is_docker_available()
            if docker_status.available:
                patterns = settings.backend_container_patterns
                containers, err = await list_containers(
                    patterns, timeout=settings.DOCKER_COMMAND_TIMEOUT
                )
                if containers and not err:
                    total_cpu = 0.0
                    for c in containers:
                        cid = c.get("ID", "")
                        if cid:
                            stats, stats_err = await get_container_stats(
                                cid, timeout=settings.DOCKER_COMMAND_TIMEOUT
                            )
                            if stats and not stats_err:
                                total_cpu += stats.get("cpu_percent", 0.0)
                    total_cpu = round(total_cpu, 2)
                    logger.debug("HexaBeta CPU (docker): %.2f%%", total_cpu)
                    return {"cpu_percent": total_cpu}

        logger.warning("No HexaBeta backend processes or Docker containers found — returning 0.0")
        return {"cpu_percent": 0.0}
