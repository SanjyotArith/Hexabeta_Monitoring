"""
HexaAgent — Alerts API Router (v1).

Exposes GET /api/v1/alerts returning current active threshold/status warnings.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter

from app.core.snapshot import snapshot_manager

logger = logging.getLogger("hexa_agent.api.v1.alerts")

router = APIRouter(prefix="/alerts", tags=["Alerts"])


@router.get(
    "",
    summary="Get current operational alerts",
    description="Returns all active threshold warnings and service downtime alerts from the cached snapshot.",
)
async def get_active_alerts() -> dict[str, Any]:
    """Retrieve currently active alerts."""
    snapshot = snapshot_manager.snapshot
    alerts = snapshot.get("alerts", [])
    return {
        "success": True,
        "count": len(alerts),
        "alerts": alerts,
    }
