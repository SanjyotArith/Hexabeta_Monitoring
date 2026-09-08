"""
HexaAgent — macOS Service Checker.

Shared utilities for checking the status of macOS services
via launchctl and brew services. Used by multiple providers.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

import psutil

logger = logging.getLogger("hexa_agent.utils.service_checker")


async def check_launchctl_service(label: str) -> dict[str, Any]:
    """
    Check if a launchd service is loaded and get its PID.

    Parameters
    ----------
    label : str
        The launchd label (e.g. 'com.hexa.backend').

    Returns
    -------
    dict
        ``{"running": bool, "pid": int | None}``
    """
    import sys
    if sys.platform != "darwin":
        return {"running": False, "pid": None}

    try:
        process = await asyncio.create_subprocess_exec(
            "launchctl", "list", label,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=5)
    except (FileNotFoundError, asyncio.TimeoutError):
        return {"running": False, "pid": None}

    if process.returncode != 0:
        return {"running": False, "pid": None}

    # Parse output: launchctl list <label> outputs key-value pairs
    output = stdout.decode()
    pid: Optional[int] = None
    for line in output.splitlines():
        line = line.strip()
        if line.startswith('"PID"') or line.startswith("PID"):
            parts = line.split("=")
            if len(parts) == 2:
                try:
                    pid = int(parts[1].strip().rstrip(";"))
                except ValueError:
                    pass

    return {"running": True, "pid": pid}


async def check_brew_service(service_name: str) -> dict[str, Any]:
    """
    Check a Homebrew service status via ``brew services info --json``.

    Parameters
    ----------
    service_name : str
        The brew service name (e.g. 'postgresql@17', 'redis').

    Returns
    -------
    dict
        ``{"running": bool, "pid": int | None, "status": str}``
    """
    import sys
    if sys.platform != "darwin":
        return {"running": False, "pid": None, "status": "unknown"}

    try:
        process = await asyncio.create_subprocess_exec(
            "brew", "services", "info", service_name, "--json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=10)
    except (FileNotFoundError, asyncio.TimeoutError):
        return {"running": False, "pid": None, "status": "unknown"}

    if process.returncode != 0:
        return {"running": False, "pid": None, "status": "unknown"}

    try:
        data = json.loads(stdout.decode())
    except json.JSONDecodeError:
        return {"running": False, "pid": None, "status": "unknown"}

    # brew services info returns a list
    if isinstance(data, list) and data:
        svc = data[0]
    elif isinstance(data, dict):
        svc = data
    else:
        return {"running": False, "pid": None, "status": "unknown"}

    running = svc.get("running", False)
    pid = svc.get("pid")
    status = svc.get("status", "unknown")

    return {"running": bool(running), "pid": pid, "status": status}


def get_process_metrics(pid: int) -> dict[str, Any]:
    """
    Get CPU and memory metrics for a process by PID.

    Returns
    -------
    dict
        ``{"cpu_percent": float, "memory_bytes": int, "memory_mb": float}``
        or zeroed values if the process is not found.
    """
    try:
        proc = psutil.Process(pid)
        cpu = proc.cpu_percent(interval=None)
        mem = proc.memory_info()
        return {
            "cpu_percent": round(cpu, 2),
            "memory_bytes": mem.rss,
            "memory_mb": round(mem.rss / (1024 * 1024), 2),
        }
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return {"cpu_percent": 0.0, "memory_bytes": 0, "memory_mb": 0.0}


def find_process_by_name(name: str) -> Optional[psutil.Process]:
    """
    Find the first process whose name or cmdline contains *name*.

    Returns the ``psutil.Process`` or ``None``.
    """
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            proc_name = proc.info.get("name", "") or ""
            cmdline = " ".join(proc.info.get("cmdline") or [])
            if name in proc_name or name in cmdline:
                return proc
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return None


def update_cloudflared_launchagent() -> None:
    """
    Updates the Cloudflared LaunchAgent plist to redirect StandardOutPath
    and StandardErrorPath to a persistent log file, and ensures the log file exists.
    """
    import os
    import sys
    import plistlib
    from pathlib import Path

    if sys.platform != "darwin":
        logger.info("Non-macOS platform detected (%s). Skipping Cloudflared LaunchAgent update.", sys.platform)
        return

    target_log = "/Users/hexabeta/.cloudflared/cloudflared.log"
    try:
        log_path = Path(target_log)
        # Ensure parent directory exists
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if not log_path.exists():
            log_path.touch(exist_ok=True)
            try:
                log_path.chmod(0o666)
            except Exception:
                pass
            logger.info("Created cloudflared log file at %s", target_log)
    except Exception as e:
        logger.error("Failed to ensure cloudflared log file exists: %s", e)

    plist_paths = [
        Path("/Users/hexabeta/Library/LaunchAgents/homebrew.mxcl.cloudflared.plist"),
        Path("/Users/hexabeta/Library/LaunchAgents/com.oring.cloudflared.plist"),
        Path("/Library/LaunchDaemons/com.cloudflare.cloudflared.plist"),
        Path("/Users/hexabeta/Library/LaunchAgents/com.cloudflare.tunnel.plist"),
        Path("/Library/LaunchAgents/com.cloudflare.tunnel.plist"),
    ]

    updated_any = False
    for plist_path in plist_paths:
        if plist_path.exists():
            try:
                # Check permissions - if not writable, skip
                if not os.access(plist_path, os.W_OK):
                    logger.warning("Cloudflared plist %s is not writable. Skipping update.", plist_path)
                    continue

                with open(plist_path, "rb") as fp:
                    pl = plistlib.load(fp)

                updated = False
                if pl.get("StandardOutPath") != target_log:
                    pl["StandardOutPath"] = target_log
                    updated = True
                if pl.get("StandardErrorPath") != target_log:
                    pl["StandardErrorPath"] = target_log
                    updated = True

                if updated:
                    with open(plist_path, "wb") as fp:
                        plistlib.dump(pl, fp)
                    logger.info("Successfully updated Cloudflared plist %s StandardOutPath/StandardErrorPath to %s", plist_path, target_log)
                    updated_any = True
            except Exception as e:
                logger.error("Failed to update Cloudflared LaunchAgent plist %s: %s", plist_path, e)

    if not updated_any:
        logger.info("No Cloudflared LaunchAgent plists were modified.")
