"""
HexaAgent — Reporter Module.

Handles connectivity between HexaAgent and HexaMonitor.
Collects metrics and securely pushes them on a scheduled interval.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from app.core.config import get_settings
from app.core.registry import collector_registry

logger = logging.getLogger("hexa_agent.reporter")

class Reporter:
    """Background reporter that pushes metrics to HexaMonitor."""
    
    def __init__(self):
        self.settings = get_settings()
        self.agent_version = "1.0.0"
        self._task: Optional[asyncio.Task] = None
        self._client: Optional[httpx.AsyncClient] = None
        
    async def _init_client(self):
        """Initialize the HTTP client if not already done."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self.settings.REQUEST_TIMEOUT,
                verify=self.settings.VERIFY_SSL,
                headers={
                    "Authorization": f"Bearer {self.settings.AGENT_KEY}",
                    "Content-Type": "application/json"
                }
            )

    async def _collect_and_build_payload(self) -> dict[str, Any]:
        """Collect metrics and build the final report payload."""
        # Reuse existing collection logic without HTTP calls to localhost
        system_metrics = await collector_registry.collect_all()
        
        return {
            "machine_information": {
                "name": self.settings.MACHINE_NAME,
            },
            "project": self.settings.PROJECT_NAME,
            "environment": self.settings.ENVIRONMENT,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "system_metrics": system_metrics,
            "agent_version": self.agent_version
        }

    async def _send_report(self, payload: dict[str, Any]) -> None:
        """Send the report to HexaMonitor with exponential backoff on failure."""
        url = self.settings.full_report_url
        max_retries = 3
        base_delay = 5  # seconds
        
        await self._init_client()

        for attempt in range(1, max_retries + 1):
            try:
                response = await self._client.post(url, json=payload)
                response.raise_for_status()
                logger.info("Report sent successfully to HexaMonitor.")
                return  # Success
                
            except httpx.HTTPStatusError as e:
                logger.error(
                    "HTTP Status Error %s sending report to HexaMonitor: %s",
                    e.response.status_code, e.response.text
                )
                if e.response.status_code in (401, 403):
                    logger.error("Authentication failed. Check AGENT_KEY.")
                    # Do not terminate, but auth errors won't resolve on immediate retry.
                    break 
                    
            except httpx.TimeoutException:
                logger.error("Timeout sending report to HexaMonitor.")
            except httpx.ConnectError:
                logger.error("Connection refused to HexaMonitor.")
            except Exception as e:
                logger.exception("Unexpected exception sending report to HexaMonitor: %s", e)

            # Retry logic with exponential backoff
            if attempt < max_retries:
                delay = base_delay * (2 ** (attempt - 1))
                logger.warning("Retry attempt %d in %d seconds...", attempt, delay)
                await asyncio.sleep(delay)
            else:
                logger.error("Failed to send report after %d attempts. Will retry next collection cycle.", max_retries)

    async def _reporting_loop(self):
        """The main background loop that runs every COLLECTION_INTERVAL seconds."""
        logger.info("Reporter started. Interval: %d seconds. URL: %s", 
                    self.settings.COLLECTION_INTERVAL, self.settings.full_report_url)
        
        if not self.settings.AGENT_KEY:
            logger.warning("AGENT_KEY is empty. Authentication will likely fail.")
            
        while True:
            try:
                payload = await self._collect_and_build_payload()
                logger.debug("Generated report payload.")
                await self._send_report(payload)
            except asyncio.CancelledError:
                logger.info("Reporter loop cancelled.")
                break
            except Exception as e:
                logger.exception("Unexpected error in reporting loop: %s", e)
            
            try:
                await asyncio.sleep(self.settings.COLLECTION_INTERVAL)
            except asyncio.CancelledError:
                logger.info("Reporter loop cancelled during sleep.")
                break

    def start(self):
        """Start the reporter background task."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._reporting_loop())

    async def stop(self):
        """Stop the reporter background task and close the client cleanly."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        
        logger.info("Reporter stopped and HTTP client closed.")

reporter = Reporter()
