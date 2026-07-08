"""
HexaAgent — Snapshot Manager (Phase 2A).

The heart of HexaAgent. Runs a background loop that collects ALL
metrics every SNAPSHOT_INTERVAL seconds and stores them as ONE
immutable in-memory snapshot.

The API endpoint returns the cached snapshot instantly — no expensive
shell commands are ever executed inside request handlers.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

from app.core.config import get_settings
from app.core.registry import collector_registry

logger = logging.getLogger("hexa_agent.snapshot")

# Mapping from collector names to snapshot sections.
# This determines how the flat registry output is reshaped into
# the nested snapshot format.
_SECTION_MAP: dict[str, tuple[str, str]] = {
    # collector_name: (section, key_in_section)
    "cpu": ("resources", "cpu"),
    "memory": ("resources", "memory"),
    "storage": ("resources", "storage"),
    "gpu": ("resources", "gpu"),
    "backend": ("infrastructure", "backend"),
    "postgres": ("infrastructure", "postgres"),
    "redis": ("infrastructure", "redis"),
    "nginx": ("infrastructure", "nginx"),
    "cloudflared": ("infrastructure", "cloudflared"),
    "git": ("deployment", "git"),
    "availability": ("availability", "_root"),  # special: spread into section
    "system": ("system", "_root"),  # special: spread into section
    "api": ("api", "_root"),  # Phase 3
}


class SnapshotManager:
    """
    Background snapshot engine.

    Refreshes every ``SNAPSHOT_INTERVAL`` seconds. The latest snapshot
    is stored in memory and returned instantly by the API.
    """

    def __init__(self) -> None:
        self._snapshot: Optional[dict[str, Any]] = None
        self._task: Optional[asyncio.Task] = None
        self._last_refresh_ms: float = 0.0

    @property
    def snapshot(self) -> dict[str, Any]:
        """
        Return the latest cached snapshot.

        If no snapshot has been collected yet, returns a stub.
        """
        if self._snapshot is None:
            return {
                "success": False,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "message": "Snapshot not yet available. First collection in progress.",
                "resources": {},
                "infrastructure": {},
                "deployment": {},
                "availability": {},
                "system": {},
                "api": {},
                "alerts": [],
                "maintenance": False,
                "operation_queue": {"active": None, "pending": [], "pending_count": 0},
                "latest_audit_record": None,
                "history_summary": {"recorded_snapshots": 0},
            }
        return self._snapshot

    async def _refresh(self) -> None:
        """Collect all metrics and build a new snapshot."""
        start = time.monotonic()

        try:
            raw = await collector_registry.collect_all()
        except Exception:
            logger.exception("Fatal error during snapshot collection")
            return

        # Reshape into nested format
        snapshot: dict[str, Any] = {
            "success": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "resources": {},
            "infrastructure": {},
            "deployment": {},
            "availability": {},
            "system": {},
            "api": {},
            "alerts": [],
            "maintenance": False,
            "operation_queue": {},
            "latest_audit_record": None,
            "history_summary": {},
        }

        for collector_name, data in raw.items():
            mapping = _SECTION_MAP.get(collector_name)
            if mapping is None:
                # Unknown collector — put it in a catch-all
                snapshot.setdefault("extras", {})[collector_name] = data
                continue

            section, key = mapping

            if key == "_root":
                # Spread directly into the section (system, availability)
                snapshot[section] = data
            else:
                snapshot[section][key] = data

        # ---- Phase 2B Extensions ----
        try:
            from app.core.alerts import evaluate_alerts
            from app.core.history import history_engine
            from app.core.maintenance import maintenance_manager
            from app.core.operations import audit_logger, queue_manager

            # Evaluated Alerts
            snapshot["alerts"] = evaluate_alerts(snapshot)
            
            # Maintenance Mode Status
            snapshot["maintenance"] = maintenance_manager.is_enabled
            
            # Operation Queue status
            snapshot["operation_queue"] = queue_manager.get_queue_status()
            
            # Latest Audit Record
            snapshot["latest_audit_record"] = audit_logger.get_latest_record()
            
            # History summary
            snapshot["history_summary"] = history_engine.get_history_summary()
        except Exception as e:
            logger.error("Failed to append Phase 2B extensions to snapshot: %s", e)

        elapsed = (time.monotonic() - start) * 1000
        self._last_refresh_ms = elapsed
        self._snapshot = snapshot

        logger.debug("Snapshot refreshed in %.1fms", elapsed)


    async def _loop(self) -> None:
        """Background loop — refreshes snapshot every SNAPSHOT_INTERVAL seconds."""
        settings = get_settings()
        interval = settings.SNAPSHOT_INTERVAL

        logger.info(
            "SnapshotManager started — refreshing every %d seconds", interval
        )

        # Perform the first collection immediately
        await self._refresh()

        while True:
            try:
                await asyncio.sleep(interval)
                await self._refresh()
            except asyncio.CancelledError:
                logger.info("SnapshotManager loop cancelled")
                break
            except Exception:
                logger.exception("Error in snapshot loop — will retry next cycle")

    def start(self) -> None:
        """Start the background refresh loop."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        """Cancel the background refresh loop."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("SnapshotManager stopped")


# Module-level singleton
snapshot_manager = SnapshotManager()
