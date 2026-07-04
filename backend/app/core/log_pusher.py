"""
HexaAgent — Log Pusher Module.

Tails log files for configured services and pushes new log lines
to HexaMonitor every LOGS_PUSH_INTERVAL seconds via HTTP POST.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Optional
import httpx

from app.core.config import get_settings
from app.core.logs import get_log_path

logger = logging.getLogger("hexa_agent.log_pusher")


class LogPusher:
    """Background service that tails local service log files and pushes new lines to HexaMonitor."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._task: Optional[asyncio.Task] = None
        self._client: Optional[httpx.AsyncClient] = None
        # Maps service name -> current byte offset in file
        self._offsets: dict[str, int] = {}
        # List of services to tail
        self.services = [
            "backend",
            "backend_error",
            "nginx",
            "nginx_error",
            "redis",
            "postgres",
            "cloudflared",
            "deployment",
        ]

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

    def _initialize_offsets(self) -> None:
        """Seek to the end of all existing log files on startup so we only push new lines."""
        for service in self.services:
            path = get_log_path(service)
            if path and path.exists():
                try:
                    self._offsets[service] = path.stat().st_size
                    logger.info("LogPusher initialized offset for '%s' to %d", service, self._offsets[service])
                except Exception as e:
                    logger.error("Failed to initialize offset for '%s': %s", service, e)
                    self._offsets[service] = 0
            else:
                self._offsets[service] = 0

    async def _push_service_logs(self, service: str, lines: list[str]) -> None:
        """POST the log lines to HexaMonitor."""
        url = self.settings.full_logs_push_url
        await self._init_client()

        payload = {
            "machine_name": self.settings.MACHINE_NAME,
            "project": self.settings.PROJECT_NAME,
            "environment": self.settings.ENVIRONMENT,
            "service": service,
            "lines": lines,
        }

        try:
            logger.info("Pushing %d log lines for service '%s' to %s", len(lines), service, url)
            response = await self._client.post(url, json=payload)
            if response.status_code not in (200, 201):
                logger.error(
                    "Failed to push logs for service '%s'. HTTP %d: %s",
                    service,
                    response.status_code,
                    response.text,
                )
            else:
                logger.debug("Successfully pushed logs for service '%s'", service)

        except httpx.HTTPStatusError as e:
            logger.error(
                "HTTP Status Error %d pushing logs for '%s' to HexaMonitor: %s",
                e.response.status_code,
                service,
                e.response.text,
            )
        except httpx.TimeoutException as e:
            logger.error("Timeout exception pushing logs for '%s' to HexaMonitor: %s", service, e)
        except httpx.ConnectError as e:
            logger.error("Connection error pushing logs for '%s' to HexaMonitor: %s", service, e)
        except Exception as e:
            logger.exception("Unexpected exception pushing logs for '%s': %s", service, e)

    async def _read_and_push_new_lines(self) -> None:
        """Check all service log files for new content and push it."""
        for service in self.services:
            path = get_log_path(service)
            if not path or not path.exists():
                # Reset offset to 0 so when the file is created, we read it from the beginning
                self._offsets[service] = 0
                continue

            try:
                current_size = path.stat().st_size
                last_offset = self._offsets.get(service, 0)

                # If file was rotated or truncated
                if current_size < last_offset:
                    logger.info("Log file for '%s' was rotated/truncated. Resetting offset.", service)
                    last_offset = 0

                if current_size == last_offset:
                    continue

                # Read newly appended content
                new_lines = []
                with open(path, "rb") as f:
                    f.seek(last_offset)
                    data = f.read(current_size - last_offset)
                    self._offsets[service] = current_size

                    if data:
                        lines_raw = data.split(b"\n")
                        for line_raw in lines_raw:
                            try:
                                line = line_raw.decode("utf-8").strip()
                                if line:
                                    new_lines.append(line)
                            except UnicodeDecodeError:
                                continue

                # Push if we found any valid new lines
                if new_lines:
                    await self._push_service_logs(service, new_lines)

            except Exception as e:
                logger.error("Error reading log file for service '%s': %s", service, e)

    async def _loop(self) -> None:
        """Main background loop executing every LOGS_PUSH_INTERVAL seconds."""
        self._initialize_offsets()
        interval = self.settings.LOGS_PUSH_INTERVAL
        logger.info(
            "LogPusher started — pushing to %s every %d seconds",
            self.settings.full_logs_push_url,
            interval,
        )

        while True:
            try:
                await self._read_and_push_new_lines()
            except asyncio.CancelledError:
                logger.info("LogPusher loop cancelled.")
                break
            except Exception as e:
                logger.exception("Unexpected error in LogPusher loop: %s", e)

            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                logger.info("LogPusher loop cancelled during sleep.")
                break

    def start(self) -> None:
        """Start the log pusher background task."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        """Stop the log pusher background task and close the client cleanly."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        if self._client and not self._client.is_closed:
            await self._client.aclose()

        logger.info("LogPusher stopped and HTTP client closed.")


# Module-level singleton
log_pusher = LogPusher()
