"""
HexaAgent — Memory (RAM) Collector.

Aggregates RSS memory usage across all HexaBeta uvicorn processes.
"""

from __future__ import annotations

import logging
from typing import Any

import psutil

from app.core.config import get_settings
from app.core.registry import BaseCollector
from app.utils.process_finder import find_hexabeta_processes

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
        Return the combined RSS memory of all HexaBeta processes.

        Returns
        -------
        dict
            ``{"memory_bytes": int, "memory_mb": float, "memory_gb": float}``
        """
        settings = get_settings()
        processes = find_hexabeta_processes(settings)

        if not processes:
            logger.warning("No HexaBeta processes found — returning 0")
            return {
                "memory_bytes": 0,
                "memory_mb": 0.0,
                "memory_gb": 0.0,
            }

        total_rss: int = 0
        for proc in processes:
            try:
                mem_info = proc.memory_info()
                total_rss += mem_info.rss
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        memory_mb = round(total_rss / _BYTES_PER_MB, 2)
        memory_gb = round(total_rss / _BYTES_PER_GB, 4)

        logger.debug("HexaBeta memory: %d bytes (%.2f MB)", total_rss, memory_mb)
        return {
            "memory_bytes": total_rss,
            "memory_mb": memory_mb,
            "memory_gb": memory_gb,
        }
