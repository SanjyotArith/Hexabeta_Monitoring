"""
HexaAgent — Docker CLI Utility.

Provides safe, read-only access to the Docker CLI for detecting
and inspecting containers.  Used by providers that need Docker
awareness (primarily BackendProvider).

Design principles:
    - READ-ONLY: only ``docker ps``, ``docker inspect``, ``docker stats``,
      ``docker info`` — never ``restart``, ``stop``, ``kill``, ``exec``.
    - No ``shell=True`` — all commands via ``create_subprocess_exec``.
    - All calls have explicit timeouts.
    - All failures return structured data; nothing raises to the caller.
    - Docker availability is cached after first probe.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("hexa_agent.utils.docker")

# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class ContainerInfo:
    """Structured representation of a running Docker container."""
    id: str
    name: str
    image: str
    status: str
    state: str
    health: Optional[str] = None
    cpu_percent: float = 0.0
    memory_bytes: int = 0
    memory_mb: float = 0.0
    memory_limit_bytes: Optional[int] = None
    uptime_seconds: Optional[float] = None
    ports: Optional[str] = None
    created: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "image": self.image,
            "status": self.status,
            "state": self.state,
            "health": self.health,
            "cpu_percent": self.cpu_percent,
            "memory_bytes": self.memory_bytes,
            "memory_mb": self.memory_mb,
            "memory_limit_bytes": self.memory_limit_bytes,
            "uptime_seconds": self.uptime_seconds,
            "ports": self.ports,
            "created": self.created,
        }


@dataclass
class DockerStatus:
    """Result of a Docker availability check."""
    available: bool = False
    error: Optional[str] = None
    version: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers — subprocess execution
# ---------------------------------------------------------------------------

async def _run_docker_cmd(
    *args: str,
    timeout: int = 5,
) -> tuple[Optional[str], Optional[str]]:
    """
    Execute a Docker CLI command and return (stdout, error_message).

    Returns (stdout_text, None) on success, or (None, error_string) on failure.
    Never raises.
    """
    try:
        process = await asyncio.create_subprocess_exec(
            "docker", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=timeout
        )

        if process.returncode != 0:
            err_text = stderr.decode(errors="replace").strip()
            # Sanitize — don't log potentially sensitive content in full
            if len(err_text) > 200:
                err_text = err_text[:200] + "..."
            return None, f"docker {' '.join(args)} failed (rc={process.returncode}): {err_text}"

        return stdout.decode(errors="replace").strip(), None

    except FileNotFoundError:
        return None, "Docker CLI not found"
    except asyncio.TimeoutError:
        return None, f"docker {' '.join(args)} timed out after {timeout}s"
    except PermissionError:
        return None, "Permission denied accessing Docker"
    except Exception as e:
        return None, f"Unexpected error running docker command: {type(e).__name__}"


# ---------------------------------------------------------------------------
# Docker Availability (cached)
# ---------------------------------------------------------------------------

_cached_docker_status: Optional[DockerStatus] = None


async def is_docker_available(*, force_recheck: bool = False) -> DockerStatus:
    """
    Check whether the Docker CLI is installed and the daemon is reachable.

    Result is cached after the first successful/failed probe to avoid
    running ``docker info`` every snapshot cycle.  Pass
    ``force_recheck=True`` to bypass the cache.
    """
    global _cached_docker_status

    if _cached_docker_status is not None and not force_recheck:
        return _cached_docker_status

    status = DockerStatus()

    stdout, err = await _run_docker_cmd("info", "--format", "{{.ServerVersion}}", timeout=5)
    if err:
        status.available = False
        status.error = err
        logger.debug("Docker not available: %s", err)
    else:
        status.available = True
        status.version = stdout
        logger.info("Docker available — server version: %s", stdout)

    _cached_docker_status = status
    return status


def reset_docker_cache() -> None:
    """Reset the cached Docker availability status (useful for testing)."""
    global _cached_docker_status
    _cached_docker_status = None


# ---------------------------------------------------------------------------
# Container Listing
# ---------------------------------------------------------------------------

async def list_containers(
    name_patterns: list[str],
    *,
    timeout: int = 5,
) -> tuple[list[dict[str, Any]], Optional[str]]:
    """
    List running Docker containers whose names match any of the given patterns.

    Parameters
    ----------
    name_patterns : list[str]
        Substrings to match against container names
        (e.g. ``["hexabeta_backend", "hexabeta_backend_green"]``).
    timeout : int
        Command timeout in seconds.

    Returns
    -------
    tuple[list[dict], Optional[str]]
        (list_of_container_dicts, error_message_or_None)
    """
    if not name_patterns:
        return [], "No container name patterns configured"

    # Use docker ps with JSON format for reliable parsing
    format_str = (
        '{"ID":"{{.ID}}",'
        '"Name":"{{.Names}}",'
        '"Image":"{{.Image}}",'
        '"Status":"{{.Status}}",'
        '"State":"{{.State}}",'
        '"Ports":"{{.Ports}}",'
        '"CreatedAt":"{{.CreatedAt}}"}'
    )

    stdout, err = await _run_docker_cmd(
        "ps", "--no-trunc", "--format", format_str,
        timeout=timeout,
    )

    if err:
        return [], err

    if not stdout:
        return [], None  # No containers running at all — not an error

    containers: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            container = json.loads(line)
        except json.JSONDecodeError:
            logger.debug("Skipping malformed docker ps line: %.100s", line)
            continue

        container_name = container.get("Name", "")
        # Check if the container name matches any of our patterns
        if any(pattern in container_name for pattern in name_patterns):
            containers.append(container)

    return containers, None


# ---------------------------------------------------------------------------
# Container Inspection
# ---------------------------------------------------------------------------

async def inspect_container(
    container_id: str,
    *,
    timeout: int = 5,
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """
    Run ``docker inspect`` on a single container.

    Returns (inspection_dict, error_or_None).
    """
    stdout, err = await _run_docker_cmd(
        "inspect", container_id,
        timeout=timeout,
    )

    if err:
        return None, err

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return None, "Failed to parse docker inspect output"

    if isinstance(data, list) and data:
        return data[0], None
    elif isinstance(data, dict):
        return data, None

    return None, "Empty docker inspect result"


# ---------------------------------------------------------------------------
# Container Stats (CPU / Memory)
# ---------------------------------------------------------------------------

async def get_container_stats(
    container_id: str,
    *,
    timeout: int = 10,
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """
    Run ``docker stats --no-stream`` for a single container.

    Returns a dict with cpu_percent, memory_bytes, memory_limit_bytes,
    or (None, error).
    """
    format_str = (
        '{"CPUPerc":"{{.CPUPerc}}",'
        '"MemUsage":"{{.MemUsage}}",'
        '"MemPerc":"{{.MemPerc}}"}'
    )

    stdout, err = await _run_docker_cmd(
        "stats", "--no-stream", "--format", format_str, container_id,
        timeout=timeout,
    )

    if err:
        return None, err

    if not stdout:
        return None, "Empty stats output"

    try:
        raw = json.loads(stdout.strip())
    except json.JSONDecodeError:
        return None, "Failed to parse docker stats output"

    result: dict[str, Any] = {
        "cpu_percent": _parse_percent(raw.get("CPUPerc", "0%")),
        "memory_bytes": 0,
        "memory_limit_bytes": None,
    }

    # Parse "MemUsage": "300MiB / 1GiB"
    mem_usage = raw.get("MemUsage", "")
    if " / " in mem_usage:
        used_str, limit_str = mem_usage.split(" / ", 1)
        result["memory_bytes"] = _parse_size(used_str.strip())
        result["memory_limit_bytes"] = _parse_size(limit_str.strip())
    elif mem_usage:
        result["memory_bytes"] = _parse_size(mem_usage.strip())

    return result, None


# ---------------------------------------------------------------------------
# Container Health from Inspect
# ---------------------------------------------------------------------------

def extract_health_from_inspect(
    inspection: dict[str, Any],
) -> Optional[str]:
    """
    Extract the Docker health status from an inspect result.

    Returns ``"healthy"``, ``"unhealthy"``, ``"starting"``, or ``None``
    if no healthcheck is configured.
    """
    state = inspection.get("State", {})
    health = state.get("Health", {})
    return health.get("Status") if health else None


def extract_started_at(inspection: dict[str, Any]) -> Optional[str]:
    """Extract the container StartedAt timestamp from inspect data."""
    state = inspection.get("State", {})
    return state.get("StartedAt")


# ---------------------------------------------------------------------------
# Size / Percent Parsers
# ---------------------------------------------------------------------------

def _parse_percent(s: str) -> float:
    """Parse '12.34%' → 12.34.  Returns 0.0 on failure."""
    try:
        return float(s.rstrip("%"))
    except (ValueError, TypeError):
        return 0.0


def _parse_size(s: str) -> int:
    """
    Parse Docker memory strings like '300MiB', '1.5GiB', '512KiB', '1024B'.

    Returns bytes as int.  Returns 0 on failure.
    """
    s = s.strip()
    if not s:
        return 0

    multipliers = {
        "B": 1,
        "KIB": 1024,
        "MIB": 1024 ** 2,
        "GIB": 1024 ** 3,
        "TIB": 1024 ** 4,
        "KB": 1000,
        "MB": 1000 ** 2,
        "GB": 1000 ** 3,
        "TB": 1000 ** 4,
    }

    for suffix, mult in sorted(multipliers.items(), key=lambda x: -len(x[0])):
        if s.upper().endswith(suffix):
            num_str = s[: -len(suffix)].strip()
            try:
                return int(float(num_str) * mult)
            except (ValueError, TypeError):
                return 0

    # Plain number
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return 0
