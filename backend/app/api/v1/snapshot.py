"""
HexaAgent — Snapshot API Router (v1).

Exposes GET /api/v1/snapshot — the PRIMARY API for HexaMonitor.
Returns the cached in-memory snapshot instantly (no collection happens here).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter

from app.core.snapshot import snapshot_manager

logger = logging.getLogger("hexa_agent.api.v1.snapshot")

router = APIRouter(prefix="/snapshot", tags=["Snapshot"])


@router.get(
    "",
    summary="Get unified HexaBeta production snapshot",
    description=(
        "Returns the latest cached snapshot containing all resources, "
        "infrastructure, deployment, availability, and system metrics. "
        "This is the primary API consumed by HexaMonitor."
    ),
)
async def get_snapshot() -> dict[str, Any]:
    """
    Return the cached snapshot instantly.

    No collection happens in this handler — all data is pre-computed
    by the SnapshotManager background loop.
    """
    return snapshot_manager.snapshot
