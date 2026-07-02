"""
HexaAgent — GPU Collector.

Collects GPU information on macOS via ``system_profiler``.
Live utilisation is returned as ``null`` because macOS does not
expose reliable per-process GPU metrics without kernel extensions.
"""

from __future__ import annotations

import asyncio
import json
import logging
import platform
from typing import Any, Optional

from app.core.registry import BaseCollector

logger = logging.getLogger("hexa_agent.collectors.gpu")


class GpuCollector(BaseCollector):
    """Collect static GPU information on macOS."""

    @property
    def name(self) -> str:
        return "gpu"

    async def collect(self) -> dict[str, Any]:
        """
        Return GPU model, vendor, core count, Metal support, and
        utilisation (always ``null`` on macOS).

        Falls back gracefully to ``null`` values if not on macOS
        or if ``system_profiler`` is unavailable.
        """
        if platform.system() != "Darwin":
            logger.info("Not running on macOS — GPU info unavailable")
            return _empty_gpu_info()

        try:
            gpu_data = await _query_system_profiler()
            if gpu_data is None:
                return _empty_gpu_info()
            return gpu_data
        except Exception:
            logger.exception("Failed to collect GPU information")
            return _empty_gpu_info()


async def _query_system_profiler() -> Optional[dict[str, Any]]:
    """
    Run ``system_profiler SPDisplaysDataType -json`` and parse the output.

    Returns a dict with gpu info or ``None`` on failure.
    """
    try:
        process = await asyncio.create_subprocess_exec(
            "system_profiler",
            "SPDisplaysDataType",
            "-json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10)
    except FileNotFoundError:
        logger.warning("system_profiler not found")
        return None
    except asyncio.TimeoutError:
        logger.warning("system_profiler timed out")
        return None

    if process.returncode != 0:
        logger.warning(
            "system_profiler exited with code %d: %s",
            process.returncode,
            stderr.decode().strip(),
        )
        return None

    try:
        data = json.loads(stdout.decode())
    except json.JSONDecodeError:
        logger.warning("Failed to parse system_profiler JSON output")
        return None

    displays = data.get("SPDisplaysDataType", [])
    if not displays:
        return _empty_gpu_info()

    gpu = displays[0]

    model: Optional[str] = gpu.get("sppci_model", None)
    vendor: Optional[str] = gpu.get("sppci_vendor", None)

    # Core count — Apple Silicon reports "gpu_core_count",
    # while some AMD/Intel GPUs may not include it.
    cores: Optional[int] = None
    raw_cores = gpu.get("sppci_cores")
    if raw_cores is not None:
        try:
            cores = int(raw_cores)
        except (ValueError, TypeError):
            pass

    # Metal support
    metal_support: Optional[str] = gpu.get("spdisplays_metal", None)
    metal_supported: Optional[bool] = None
    if metal_support is not None:
        metal_supported = "supported" in metal_support.lower()

    return {
        "model": model,
        "vendor": vendor,
        "core_count": cores,
        "metal_supported": metal_supported,
        "utilization": None,  # Not reliably available on macOS
    }


def _empty_gpu_info() -> dict[str, Any]:
    """Return a dict with all GPU fields set to ``None``."""
    return {
        "model": None,
        "vendor": None,
        "core_count": None,
        "metal_supported": None,
        "utilization": None,
    }
