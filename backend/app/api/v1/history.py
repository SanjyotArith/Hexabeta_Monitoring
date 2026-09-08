"""
HexaAgent — History API Router (v1).

Exposes GET /api/v1/history returning periodic snapshots history list.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Query

from app.core.history import history_engine

logger = logging.getLogger("hexa_agent.api.v1.history")

router = APIRouter(prefix="/history", tags=["History"])


@router.get(
    "",
    summary="Get historical snapshot data",
    description="Returns list of historical operational metrics snapshots recorded periodically.",
)
async def get_historical_snapshots(
    limit: int = Query(100, ge=1, le=500, description="Max history data points to fetch")
) -> dict[str, Any]:
    """Retrieve periodic snapshot metrics history."""
    history = history_engine.get_history(limit=limit)
    return {
        "success": True,
        "limit": limit,
        "count": len(history),
        "history": history,
    }
