"""
HexaAgent — Memory (RAM) Collector.

Aggregates RSS memory usage across all HexaBeta backend processes
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

logger = logging.getLogger("hexa_agent.collectors.memory")

# Conversion constants
_BYTES_PER_MB: float = 1024 * 1024
_BYTES_PER_GB: float = 1024 * 1024 * 1024


class MemoryCollector(BaseCollector):
    """Collect aggregated RSS memory for the HexaBeta backend."""

    @property
    def name(self) -> str:
        return "memory"

    async def collect(self) -> dict[str, Any]:
        """
        Return the combined RSS memory of all HexaBeta backend processes or containers.

        Returns
        -------
        dict
            ``{"memory_bytes": int, "memory_mb": float, "memory_gb": float}``
        """
        settings = get_settings()

        # Step 1: Try host processes
        processes = find_hexabeta_processes(settings)
        if processes:
            total_rss: int = 0
            for proc in processes:
                try:
                    mem_info = proc.memory_info()
                    total_rss += mem_info.rss
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue

            memory_mb = round(total_rss / _BYTES_PER_MB, 2)
            memory_gb = round(total_rss / _BYTES_PER_GB, 4)

            logger.debug("HexaBeta memory (host): %d bytes (%.2f MB)", total_rss, memory_mb)
            return {
                "memory_bytes": total_rss,
                "memory_mb": memory_mb,
                "memory_gb": memory_gb,
            }

        # Step 2: Try Docker containers if enabled
        if settings.DOCKER_ENABLED:
            docker_status = await is_docker_available()
            if docker_status.available:
                patterns = settings.backend_container_patterns
                containers, err = await list_containers(
                    patterns, timeout=settings.DOCKER_COMMAND_TIMEOUT
                )
                if containers and not err:
                    total_rss = 0
                    for c in containers:
                        cid = c.get("ID", "")
                        if cid:
                            stats, stats_err = await get_container_stats(
                                cid, timeout=settings.DOCKER_COMMAND_TIMEOUT
                            )
                            if stats and not stats_err:
                                total_rss += stats.get("memory_bytes", 0)

                    memory_mb = round(total_rss / _BYTES_PER_MB, 2)
                    memory_gb = round(total_rss / _BYTES_PER_GB, 4)

                    logger.debug("HexaBeta memory (docker): %d bytes (%.2f MB)", total_rss, memory_mb)
                    return {
                        "memory_bytes": total_rss,
                        "memory_mb": memory_mb,
                        "memory_gb": memory_gb,
                    }

        logger.warning("No HexaBeta backend processes or Docker containers found — returning 0")
        return {
            "memory_bytes": 0,
            "memory_mb": 0.0,
            "memory_gb": 0.0,
        }
