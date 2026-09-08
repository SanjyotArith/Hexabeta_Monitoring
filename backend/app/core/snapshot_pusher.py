"""
HexaAgent — Snapshot Pusher Module.

Pushes the latest cached system/infrastructure snapshot to HexaMonitor
every SNAPSHOT_INTERVAL seconds via HTTP POST.
"""

import asyncio
import json
import logging
from typing import Any, Optional

import httpx

from app.core.config import get_settings
from app.core.snapshot import snapshot_manager

logger = logging.getLogger("hexa_agent.snapshot_pusher")


class SnapshotPusher:
    """Background service that periodically pushes the cached snapshot to HexaMonitor."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._task: Optional[asyncio.Task] = None
        self._client: Optional[httpx.AsyncClient] = None

    async def _init_client(self) -> None:
        """Initialize the HTTP client if not already done."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self.settings.REQUEST_TIMEOUT,
                verify=self.settings.VERIFY_SSL,
                headers={
                    "Authorization": f"Bearer {self.settings.AGENT_KEY}",
                    "Content-Type": "application/json",
                },
            )

    async def _push_snapshot(self, payload: dict[str, Any]) -> None:
        """Send the snapshot to HexaMonitor with detailed audit logs."""
        url = self.settings.full_snapshot_push_url
        await self._init_client()

        payload_bytes = json.dumps(payload).encode("utf-8")
        payload_size = len(payload_bytes)
        snapshot_time = payload.get("timestamp", "unknown")

        logger.info(
            "Attempting to push snapshot [Created: %s] to URL: %s [Size: %d bytes]",
            snapshot_time,
            url,
            payload_size,
        )

        try:
            # We initialize client in _init_client which handles headers
            response = await self._client.post(url, json=payload)
            
            logger.info(
                "Snapshot push completed. HTTP Status Code: %d | Response: %s",
                response.status_code,
                response.text[:1000],  # Log up to 1000 characters of response body
            )
            response.raise_for_status()

        except httpx.HTTPStatusError as e:
            logger.error(
                "HTTP Status Error %d pushing snapshot to HexaMonitor: %s",
                e.response.status_code,
                e.response.text,
            )
        except httpx.TimeoutException as e:
            logger.error("Timeout exception pushing snapshot to HexaMonitor: %s", e)
        except httpx.ConnectError as e:
            logger.error("Connection error pushing snapshot to HexaMonitor: %s", e)
        except Exception as e:
            logger.exception("Unexpected exception occurred during snapshot push: %s", e)

    async def _loop(self) -> None:
        """Main background loop executing every SNAPSHOT_INTERVAL seconds."""
        interval = self.settings.SNAPSHOT_INTERVAL
        logger.info(
            "SnapshotPusher started — pushing to %s every %d seconds",
            self.settings.full_snapshot_push_url,
            interval,
        )

        while True:
            try:
                snapshot = snapshot_manager.snapshot
                if snapshot and snapshot.get("success") is True:
                    await self._push_snapshot(snapshot)
                else:
                    logger.debug("Snapshot cache not ready or failed. Skipping push cycle.")

            except asyncio.CancelledError:
                logger.info("SnapshotPusher loop cancelled.")
                break
            except Exception as e:
                logger.exception("Unexpected error in SnapshotPusher loop: %s", e)

            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                logger.info("SnapshotPusher loop cancelled during sleep.")
                break

    def start(self) -> None:
        """Start the snapshot pusher background task."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        """Stop the snapshot pusher background task and close the client cleanly."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        if self._client and not self._client.is_closed:
            await self._client.aclose()

        logger.info("SnapshotPusher stopped and HTTP client closed.")


# Module-level singleton
snapshot_pusher = SnapshotPusher()
