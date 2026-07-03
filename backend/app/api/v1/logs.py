"""
HexaAgent — Logs API Router (v1).

Exposes logs reading, tailing, regex search, and download streams for configured services.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse

from app.core.logs import get_log_path, read_logs_tail

logger = logging.getLogger("hexa_agent.api.v1.logs")

router = APIRouter(prefix="/logs", tags=["Logs"])


@router.get(
    "/{service}",
    summary="Get or download logs for a specific service",
    description=(
        "Returns tailed log lines in JSON format by default, with optional search filtering. "
        "Pass 'download=true' to retrieve the raw log file as a downloadable stream."
    ),
)
async def get_service_logs(
    service: str,
    limit: int = Query(100, ge=1, le=2000, alias="limit", description="Number of lines to tail"),
    search: Optional[str] = Query(None, description="Regular expression or text to filter logs"),
    download: bool = Query(False, description="Set to true to download the raw log file"),
) -> Any:
    """Read service log lines or fetch download response."""
    log_path = get_log_path(service)
    
    if not log_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Service logs for '{service}' are not configured or supported.",
        )

    if not log_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Log file for service '{service}' does not exist at {log_path}",
        )

    if download:
        logger.info("Streaming raw download for service logs: %s", service)
        return FileResponse(
            path=log_path,
            media_type="text/plain",
            filename=f"hexabeta_{service}_{int(limit)}_logs.log",
        )

    # Regular tail & search JSON response
    lines = read_logs_tail(service, tail_lines=limit, search_query=search)
    return {
        "success": True,
        "service": service,
        "path": str(log_path),
        "limit": limit,
        "search_filter": search,
        "line_count": len(lines),
        "lines": lines,
    }
