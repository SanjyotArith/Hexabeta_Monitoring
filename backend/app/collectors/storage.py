"""
HexaAgent — Storage Collector.

Calculates disk usage ONLY for the configured HexaBeta project paths.
Never reports whole-disk or OS-level storage.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.registry import BaseCollector

logger = logging.getLogger("hexa_agent.collectors.storage")

# Conversion constants
_BYTES_PER_MB: float = 1024 * 1024
_BYTES_PER_GB: float = 1024 * 1024 * 1024


class StorageCollector(BaseCollector):
    """Calculate disk footprint for configured HexaBeta directories."""

    @property
    def name(self) -> str:
        return "storage"

    async def collect(self) -> dict[str, Any]:
        """
        Walk each configured directory and sum file sizes.

        Returns
        -------
        dict
            Byte, MB, and GB values for project, backend, frontend,
            and uploads directories.
        """
        settings = get_settings()

        project_bytes = _dir_size(settings.project_root)
        backend_bytes = _dir_size(settings.backend_path)
        frontend_bytes = _dir_size(settings.frontend_path)
        uploads_bytes = _dir_size(settings.uploads_path)

        logger.debug("HexaBeta project storage: %d bytes", project_bytes)
        return {
            "project_bytes": project_bytes,
            "project_mb": round(project_bytes / _BYTES_PER_MB, 2),
            "project_gb": round(project_bytes / _BYTES_PER_GB, 4),
            "backend_bytes": backend_bytes,
            "backend_mb": round(backend_bytes / _BYTES_PER_MB, 2),
            "backend_gb": round(backend_bytes / _BYTES_PER_GB, 4),
            "frontend_bytes": frontend_bytes,
            "frontend_mb": round(frontend_bytes / _BYTES_PER_MB, 2),
            "frontend_gb": round(frontend_bytes / _BYTES_PER_GB, 4),
            "uploads_bytes": uploads_bytes,
            "uploads_mb": round(uploads_bytes / _BYTES_PER_MB, 2),
            "uploads_gb": round(uploads_bytes / _BYTES_PER_GB, 4),
        }


def _dir_size(path: Path) -> int:
    """
    Recursively sum the size (in bytes) of all files under *path*.

    Returns 0 if the path does not exist or is inaccessible.
    """
    if not path.exists():
        logger.warning("Path does not exist: %s", path)
        return 0

    total: int = 0
    try:
        for entry in path.rglob("*"):
            if entry.is_file():
                try:
                    total += entry.stat().st_size
                except OSError:
                    # Permission denied / broken symlink — skip
                    continue
    except OSError:
        logger.exception("Failed to walk directory: %s", path)
    return total
