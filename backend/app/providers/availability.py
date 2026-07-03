"""
HexaAgent — Availability Provider (Phase 2A).

Performs two independent health checks:
    1. Internal — http://localhost:8002/api/health
    2. External — https://hexabeta.com/api/health

This allows distinguishing between backend failure, Nginx issues,
Cloudflare issues, and internet connectivity problems.

READ ONLY.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.registry import BaseCollector

logger = logging.getLogger("hexa_agent.providers.availability")


class AvailabilityProvider(BaseCollector):
    """Check HexaBeta availability from internal and external endpoints."""

    @property
    def name(self) -> str:
        return "availability"

    async def collect(self) -> dict[str, Any]:
        settings = get_settings()

        # Run both checks concurrently
        internal_task = _health_check(settings.BACKEND_INTERNAL_HEALTH_URL)
        external_task = _health_check(settings.BACKEND_EXTERNAL_HEALTH_URL)

        internal, external = await asyncio.gather(internal_task, external_task)

        return {
            "internal": internal,
            "external": external,
        }


async def _health_check(url: str) -> dict[str, Any]:
    """
    Perform a GET to the given URL and return structured results.

    Returns
    -------
    dict
        ``{"healthy": bool, "http_status": int | None,
           "response_time_ms": float, "timestamp": str, "error": str | None}``
    """
    result: dict[str, Any] = {
        "healthy": False,
        "http_status": None,
        "response_time_ms": 0.0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "error": None,
    }

    try:
        async with httpx.AsyncClient(timeout=5.0, verify=False) as client:
            start = time.monotonic()
            response = await client.get(url)
            elapsed = (time.monotonic() - start) * 1000

            result["http_status"] = response.status_code
            result["response_time_ms"] = round(elapsed, 2)
            result["healthy"] = 200 <= response.status_code < 300

    except httpx.TimeoutException:
        result["error"] = "Timeout"
    except httpx.ConnectError:
        result["error"] = "Connection refused"
    except Exception as e:
        result["error"] = str(e)

    return result
