"""
HexaAgent — GPU Collector.

Collects GPU information on macOS via ``system_profiler`` and
live GPU utilization via ``powermetrics``.

NOTE: ``powermetrics`` requires root privileges. Either run HexaAgent
as root, or configure passwordless sudo for powermetrics:
    sudo visudo -f /etc/sudoers.d/hexa-agent
    hexabeta ALL=(ALL) NOPASSWD: /usr/bin/powermetrics
"""

from __future__ import annotations

import asyncio
import json
import logging
import platform
import re
from typing import Any, Optional

from app.core.registry import BaseCollector

logger = logging.getLogger("hexa_agent.collectors.gpu")


class GpuCollector(BaseCollector):
    """Collect GPU information and utilization on macOS."""

    @property
    def name(self) -> str:
        return "gpu"

    async def collect(self) -> dict[str, Any]:
        """
        Return GPU model, vendor, core count, Metal support, and
        live GPU utilization (via powermetrics).

        Falls back gracefully to ``null`` values if not on macOS
        or if commands are unavailable.
        """
        if platform.system() != "Darwin":
            logger.info("Not running on macOS — GPU info unavailable")
            return _empty_gpu_info()

        try:
            # Collect static GPU info and live utilization concurrently
            gpu_info_task = _query_system_profiler()
            gpu_util_task = _query_gpu_utilization()
            gpu_info, utilization = await asyncio.gather(
                gpu_info_task, gpu_util_task
            )

            if gpu_info is None:
                gpu_info = _empty_gpu_info()

            gpu_info["utilization"] = utilization
            return gpu_info

        except Exception:
            logger.exception("Failed to collect GPU information")
            return _empty_gpu_info()


async def _query_system_profiler() -> Optional[dict[str, Any]]:
    """
    Run ``system_profiler SPDisplaysDataType -json`` and parse the output.

    Returns a dict with GPU info or ``None`` on failure.
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
        return None

    gpu = displays[0]

    # Model — available as both "_name" and "sppci_model"
    model: Optional[str] = gpu.get("sppci_model") or gpu.get("_name")

    # Vendor — key is "spdisplays_vendor", value like "sppci_vendor_Apple"
    vendor: Optional[str] = None
    raw_vendor = gpu.get("spdisplays_vendor")
    if raw_vendor:
        # Strip the "sppci_vendor_" prefix to get clean name
        vendor = raw_vendor.replace("sppci_vendor_", "")

    # Core count
    cores: Optional[int] = None
    raw_cores = gpu.get("sppci_cores")
    if raw_cores is not None:
        try:
            cores = int(raw_cores)
        except (ValueError, TypeError):
            pass

    # Metal support — key is "spdisplays_mtlgpufamilysupport",
    # value like "spdisplays_metal4"
    metal_support: Optional[str] = gpu.get("spdisplays_mtlgpufamilysupport")
    metal_supported: Optional[bool] = None
    metal_family: Optional[str] = None
    if metal_support is not None:
        metal_supported = "metal" in metal_support.lower()
        # Extract Metal family version (e.g. "Metal 4" from "spdisplays_metal4")
        match = re.search(r"metal(\d+)", metal_support.lower())
        if match:
            metal_family = f"Metal {match.group(1)}"

    return {
        "model": model,
        "vendor": vendor,
        "core_count": cores,
        "metal_supported": metal_supported,
        "metal_family": metal_family,
    }


async def _query_gpu_utilization() -> Optional[float]:
    """
    Get GPU active residency via ``powermetrics``.

    Requires root privileges. Returns the GPU HW active residency
    as a percentage (0-100), or ``None`` if unavailable.

    The sampling interval is 1 second (``-i 1000``).
    """
    # Try direct execution first (works if agent runs as root),
    # then fall back to sudo.
    for cmd in [
        ["powermetrics", "--samplers", "gpu_power", "-n", "1", "-i", "1000"],
        ["sudo", "-n", "powermetrics", "--samplers", "gpu_power", "-n", "1", "-i", "1000"],
    ]:
        result = await _run_powermetrics(cmd)
        if result is not None:
            return result

    logger.warning(
        "GPU utilization unavailable — powermetrics requires root. "
        "Run HexaAgent as root or add to sudoers: "
        "hexabeta ALL=(ALL) NOPASSWD: /usr/bin/powermetrics"
    )
    return None


async def _run_powermetrics(cmd: list[str]) -> Optional[float]:
    """Execute a powermetrics command and parse GPU active residency."""
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=15)
    except (FileNotFoundError, asyncio.TimeoutError):
        return None

    if process.returncode != 0:
        return None

    output = stdout.decode()

    # Look for "GPU HW active residency:" or "GPU active residency:"
    for line in output.splitlines():
        if "gpu" in line.lower() and "active residency" in line.lower():
            match = re.search(r"([\d.]+)\s*%", line)
            if match:
                return round(float(match.group(1)), 2)

    return None


def _empty_gpu_info() -> dict[str, Any]:
    """Return a dict with all GPU fields set to ``None``."""
    return {
        "model": None,
        "vendor": None,
        "core_count": None,
        "metal_supported": None,
        "metal_family": None,
        "utilization": None,
    }
