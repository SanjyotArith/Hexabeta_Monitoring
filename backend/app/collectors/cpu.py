"""
HexaAgent — CPU Collector.

Aggregates CPU usage across all HexaBeta uvicorn processes
(main process + worker processes).
"""

from __future__ import annotations

import logging
from typing import Any

import psutil

from app.core.config import get_settings
from app.core.registry import BaseCollector
from app.utils.process_finder import find_hexabeta_processes

logger = logging.getLogger("hexa_agent.collectors.cpu")


class CpuCollector(BaseCollector):
    """Collect aggregated CPU percent for the HexaBeta backend."""

    @property
    def name(self) -> str:
        return "cpu"

    async def collect(self) -> dict[str, Any]:
        """
        Return the combined CPU usage of all HexaBeta processes.

        ``cpu_percent()`` is called twice on each process: the first call
        initialises the measurement (returns 0.0), and after a brief
        interval the second call returns the actual value.  Because
        ``find_hexabeta_processes`` is invoked per request and psutil
        keeps internal state per-PID, repeated API calls naturally
        produce accurate readings.

        Returns
        -------
        dict
            ``{"cpu_percent": <float>}``
        """
        settings = get_settings()
        processes = find_hexabeta_processes(settings)

        if not processes:
            logger.warning("No HexaBeta processes found — returning 0.0")
            return {"cpu_percent": 0.0}

        total_cpu: float = 0.0
        for proc in processes:
            try:
                # interval=None uses the delta since the last call
                # for each PID, which is ideal for repeated polling.
                total_cpu += proc.cpu_percent(interval=None)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        total_cpu = round(total_cpu, 2)
        logger.debug("HexaBeta CPU: %.2f%%", total_cpu)
        return {"cpu_percent": total_cpu}
