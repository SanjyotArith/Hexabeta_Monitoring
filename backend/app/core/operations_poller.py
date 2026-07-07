"""
HexaAgent — Operations Poller Module.

Polls the GET /api/v1/operations/pending endpoint of HexaMonitor
every OPERATIONS_POLL_INTERVAL seconds via HTTP GET.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional, Set
import httpx

from app.core.config import get_settings
from app.core.operations import queue_manager

logger = logging.getLogger("hexa_agent.operations_poller")


class OperationsPoller:
    """Background service that periodically polls HexaMonitor for pending operations."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._task: Optional[asyncio.Task] = None
        self._client: Optional[httpx.AsyncClient] = None
        self._processed_remote_ids: Set[str] = set()

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

    async def _poll_operations(self) -> None:
        """Poll HexaMonitor for pending operations and queue them locally."""
        url = self.settings.full_operations_poll_url
        await self._init_client()

        logger.debug("Polling for pending operations at: %s", url)
        try:
            response = await self._client.get(url)
            if response.status_code == 200:
                data = response.json()
                if not data or not isinstance(data, dict):
                    logger.warning("Invalid operations polling response format.")
                    return

                # Support both response wrappers e.g. {"success": true, "operations": [...]} or just a list
                operations = data.get("operations", [])
                if not isinstance(operations, list):
                    logger.warning("Operations field is not a list in polling response.")
                    return

                for op in operations:
                    if not isinstance(op, dict):
                        continue

                    # Validate operation fields
                    service = op.get("service")
                    operation = op.get("operation")
                    mode = op.get("mode", "production")
                    remote_id = op.get("id") or op.get("operation_id") or op.get("uuid")

                    if not service or not operation:
                        logger.warning("Skipping malformed remote operation: %s", op)
                        continue

                    # De-duplicate: If we have an ID, verify if it was already processed.
                    # This prevents repeatedly queueing the same operations if the remote side
                    # takes time to clear them or they are cached.
                    if remote_id:
                        if remote_id in self._processed_remote_ids:
                            continue
                        self._processed_remote_ids.add(remote_id)

                    logger.info(
                        "Retrieved pending operation from HexaMonitor: ID=%s | service=%s | operation=%s | mode=%s",
                        remote_id,
                        service,
                        operation,
                        mode,
                    )

                    # Submit to the local execution queue manager
                    queue_manager.submit(
                        service=service,
                        operation=operation,
                        mode=mode,
                        op_id=remote_id,
                    )
            else:
                logger.error(
                    "Failed to poll operations. HTTP %d: %s",
                    response.status_code,
                    response.text,
                )

        except httpx.HTTPStatusError as e:
            logger.error(
                "HTTP Status Error %d polling operations from HexaMonitor: %s",
                e.response.status_code,
                e.response.text,
            )
        except httpx.TimeoutException as e:
            logger.error("Timeout exception polling operations from HexaMonitor: %s", e)
        except httpx.ConnectError as e:
            logger.error("Connection error polling operations from HexaMonitor: %s", e)
        except Exception as e:
            logger.exception("Unexpected exception occurred during operations poll: %s", e)

    async def _loop(self) -> None:
        """Main background loop executing every OPERATIONS_POLL_INTERVAL seconds."""
        interval = self.settings.OPERATIONS_POLL_INTERVAL
        logger.info(
            "OperationsPoller started — polling %s every %d seconds",
            self.settings.full_operations_poll_url,
            interval,
        )

        while True:
            try:
                await self._poll_operations()
            except asyncio.CancelledError:
                logger.info("OperationsPoller loop cancelled.")
                break
            except Exception as e:
                logger.exception("Unexpected error in OperationsPoller loop: %s", e)

            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                logger.info("OperationsPoller loop cancelled during sleep.")
                break

    def start(self) -> None:
        """Start the operations poller background task."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        """Stop the operations poller background task and close the client cleanly."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        if self._client and not self._client.is_closed:
            await self._client.aclose()

        logger.info("OperationsPoller stopped and HTTP client closed.")


# Module-level singleton
operations_poller = OperationsPoller()
