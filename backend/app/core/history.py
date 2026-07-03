"""
HexaAgent — History Engine (Phase 2B).

Saves historical periodic snapshots to a local SQLite database
and provides methods to query historical data.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.core.config import get_settings

logger = logging.getLogger("hexa_agent.history")


class HistoryEngine:
    """Handles snapshot persistence and historical metrics querying."""

    def __init__(self) -> None:
        self.settings = get_settings()
        # Store DB file in a backend/data directory
        self.db_dir = Path(__file__).resolve().parent.parent.parent / "data"
        self.db_path = self.db_dir / "history.db"
        self._task: Optional[asyncio.Task] = None
        self._init_db()

    def _init_db(self) -> None:
        """Initialize the SQLite database and create tables if not existing."""
        try:
            self.db_dir.mkdir(exist_ok=True)
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS snapshot_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        data TEXT NOT NULL
                    )
                    """
                )
                conn.commit()
        except Exception as e:
            logger.exception("Failed to initialize history database: %s", e)

    def record_snapshot(self, snapshot_data: dict[str, Any]) -> None:
        """Write a snapshot to the database."""
        # Only record if snapshot was successful
        if not snapshot_data.get("success", False):
            return

        try:
            # Compact snapshot to save space
            compact_data = {
                "resources": snapshot_data.get("resources", {}),
                "infrastructure": snapshot_data.get("infrastructure", {}),
                "deployment": snapshot_data.get("deployment", {}),
                "availability": snapshot_data.get("availability", {}),
                "system": snapshot_data.get("system", {}),
            }
            timestamp = snapshot_data.get("timestamp") or datetime.now(timezone.utc).isoformat()
            
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT INTO snapshot_history (timestamp, data) VALUES (?, ?)",
                    (timestamp, json.dumps(compact_data)),
                )
                conn.commit()
            logger.debug("Recorded historical snapshot at %s", timestamp)
        except Exception as e:
            logger.warning("Failed to record snapshot to history: %s", e)

    def get_history(self, limit: int = 100) -> list[dict[str, Any]]:
        """Retrieve historical snapshots, ordered by time descending."""
        history = []
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    "SELECT timestamp, data FROM snapshot_history ORDER BY id DESC LIMIT ?",
                    (limit,),
                )
                for row in cursor.fetchall():
                    try:
                        record = json.loads(row["data"])
                        record["timestamp"] = row["timestamp"]
                        history.append(record)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.error("Failed to retrieve history: %s", e)
        return history

    def get_history_summary(self) -> dict[str, Any]:
        """Return a count of recorded snapshots in the database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("SELECT count(*) FROM snapshot_history")
                count = cursor.fetchone()[0]
                return {"recorded_snapshots": count}
        except Exception:
            return {"recorded_snapshots": 0}

    async def _loop(self) -> None:
        """Background loop to periodically record snapshot history."""
        # Wait a moment for app initialization
        await asyncio.sleep(5)
        
        # Import dynamically to avoid circular import issues
        from app.core.snapshot import snapshot_manager

        logger.info(
            "History loop started. Recording snapshots every %d seconds.",
            self.settings.HISTORY_SAVE_INTERVAL,
        )

        while True:
            try:
                snapshot_data = snapshot_manager.snapshot
                self.record_snapshot(snapshot_data)
            except Exception as e:
                logger.exception("Error in history loop: %s", e)

            try:
                await asyncio.sleep(self.settings.HISTORY_SAVE_INTERVAL)
            except asyncio.CancelledError:
                logger.info("History loop cancelled.")
                break

    def start(self) -> None:
        """Start the background history recorder task."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        """Stop the background history recorder task."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("History Engine stopped.")


history_engine = HistoryEngine()
