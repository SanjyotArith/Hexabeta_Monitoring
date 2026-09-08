"""
HexaAgent — Cloudflared Provider (Phase 2A).

Monitors the Cloudflare Tunnel: process status, tunnel connectivity,
version. READ ONLY.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.core.config import get_settings
from app.core.registry import BaseCollector
from app.utils.service_checker import get_process_metrics

logger = logging.getLogger("hexa_agent.providers.cloudflared")


class CloudflaredProvider(BaseCollector):
    """Collect Cloudflare Tunnel status and metrics."""

    @property
    def name(self) -> str:
        return "cloudflared"

    async def collect(self) -> dict[str, Any]:
        settings = get_settings()
        result: dict[str, Any] = {
            "running": False,
            "tunnel_connected": False,
            "tunnel_name": settings.CLOUDFLARED_TUNNEL,
            "version": None,
            "pid": None,
            "cpu_percent": 0.0,
            "memory_bytes": 0,
            "memory_mb": 0.0,
            "last_checked": datetime.now(timezone.utc).isoformat(),
            "error": None,
        }

        try:
            # Find cloudflared process via psutil
            import psutil

            for proc in psutil.process_iter(["pid", "name", "cmdline"]):
                try:
                    cmdline = " ".join(proc.info.get("cmdline") or [])
                    if "cloudflared" in cmdline and "tunnel" in cmdline:
                        result["running"] = True
                        result["pid"] = proc.pid
                        metrics = get_process_metrics(proc.pid)
                        result["cpu_percent"] = metrics["cpu_percent"]
                        result["memory_bytes"] = metrics["memory_bytes"]
                        result["memory_mb"] = metrics["memory_mb"]
                        break
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            if not result["running"]:
                result["error"] = "Cloudflared process not found"
                return result

            # Get version
            version = await _get_version()
            result["version"] = version

            # Check tunnel connectivity
            tunnel_status = await _check_tunnel(settings.CLOUDFLARED_TUNNEL)
            result["tunnel_connected"] = tunnel_status

        except Exception as e:
            logger.exception("Cloudflared provider error: %s", e)
            result["error"] = str(e)

        return result


async def _get_version() -> Optional[str]:
    """Get cloudflared version from ``cloudflared --version``."""
    try:
        process = await asyncio.create_subprocess_exec(
            "cloudflared", "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=5)

        if process.returncode == 0:
            output = stdout.decode().strip()
            # Output format: "cloudflared version 2024.x.x (built ...)"
            parts = output.split()
            for i, part in enumerate(parts):
                if part == "version" and i + 1 < len(parts):
                    return parts[i + 1]
            return output
    except (FileNotFoundError, asyncio.TimeoutError):
        pass
    return None


async def _check_tunnel(tunnel_name: str) -> bool:
    """
    Check if the cloudflared tunnel is connected.

    Tries ``cloudflared tunnel info <name>``. If the command succeeds,
    the tunnel configuration exists (connectivity is inferred from
    the process running).
    """
    try:
        process = await asyncio.create_subprocess_exec(
            "cloudflared", "tunnel", "info", tunnel_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, _ = await asyncio.wait_for(process.communicate(), timeout=10)
        # If the process is running and tunnel info succeeds, it's connected
        return process.returncode == 0
    except (FileNotFoundError, asyncio.TimeoutError):
        pass

    # Fallback: if the cloudflared process is running with the tunnel name,
    # we consider it connected.
    return True
