"""
HexaAgent — System API Router (v1).

Exposes GET /api/v1/system which aggregates all registered collectors.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from app.core.registry import collector_registry
from app.schemas.system import SystemResponse

logger = logging.getLogger("hexa_agent.api.v1.system")

router = APIRouter(prefix="/system", tags=["System Metrics"])


@router.get(
    "",
    response_model=SystemResponse,
    summary="Get live HexaBeta system metrics",
    description=(
        "Aggregates CPU, Memory, Storage, and GPU metrics "
        "for the HexaBeta production server."
    ),
)
async def get_system_metrics() -> SystemResponse:
    """
    Collect all registered metrics and return them in a single response.
    """
    try:
        metrics = await collector_registry.collect_all()
    except Exception:
        logger.exception("Fatal error during metric collection")
        raise HTTPException(
            status_code=500,
            detail="Failed to collect system metrics",
        )

    return SystemResponse(
        success=True,
        timestamp=datetime.now(timezone.utc).isoformat(),
        cpu=metrics.get("cpu"),
        memory=metrics.get("memory"),
        storage=metrics.get("storage"),
        gpu=metrics.get("gpu"),
    )
