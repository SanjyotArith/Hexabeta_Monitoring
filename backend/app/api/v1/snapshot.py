"""
HexaMonitor & HexaAgent — Snapshot API Router (v1).

Exposes:
POST /api/v1/snapshot/push — Accepts snapshot JSON from HexaAgent and caches it in memory (requires Bearer agent key).
GET  /api/v1/snapshot      — Returns the cached snapshot instantly to the dashboard or consumer.
"""

from __future__ import annotations

import logging
from typing import Any
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Depends

from app.api.v1.operations import _AUDIT_RECORDS, _clean_stale_operations
from app.api.deps import verify_agent_key

logger = logging.getLogger("hexamonitor.api.v1.snapshot")

router = APIRouter(prefix="/snapshot", tags=["Snapshot"])

# In-memory cache for the latest pushed snapshot
_LATEST_SNAPSHOT: dict[str, Any] = {}


def _merge_operations_into_snapshot(snapshot_data: dict[str, Any]) -> dict[str, Any]:
    if not snapshot_data:
        return snapshot_data

    try:
        _clean_stale_operations()
    except Exception:
        pass

    records = list(_AUDIT_RECORDS.values())

    if records:
        records.sort(key=lambda x: x.get("timestamp", datetime.now(timezone.utc)), reverse=True)
        latest_record = records[0]

        agent_audit = snapshot_data.get("latest_audit_record")
        if agent_audit:
            op_id = agent_audit.get("id")
            if op_id and op_id in _AUDIT_RECORDS:
                if _AUDIT_RECORDS[op_id]["status"] in ["pending", "running"]:
                    new_status = agent_audit.get("status")
                    if new_status in ["success", "failed", "running"]:
                        _AUDIT_RECORDS[op_id]["status"] = new_status
                        if new_status in ["success", "failed"]:
                            _AUDIT_RECORDS[op_id]["finished_at"] = datetime.now(timezone.utc)
            else:
                for rec in _AUDIT_RECORDS.values():
                    if (
                        rec["status"] in ["pending", "running"]
                        and agent_audit.get("service") == rec["service"]
                        and agent_audit.get("operation") == rec["operation"]
                    ):
                        new_status = agent_audit.get("status")
                        if new_status in ["success", "failed", "running"]:
                            rec["status"] = new_status
                            if new_status in ["success", "failed"]:
                                rec["finished_at"] = datetime.now(timezone.utc)
                        break

        snapshot_data["latest_audit_record"] = {
            "id": latest_record["id"],
            "service": latest_record["service"],
            "operation": latest_record["operation"],
            "status": latest_record["status"],
        }
    else:
        if "latest_audit_record" in snapshot_data:
            del snapshot_data["latest_audit_record"]

    pending_ops = [op for op in _AUDIT_RECORDS.values() if op.get("status") == "pending"]
    snapshot_data["operation_queue"] = {
        "pending": [{"id": op["id"], "service": op["service"], "operation": op["operation"]} for op in pending_ops],
        "pending_count": len(pending_ops),
        "active": snapshot_data.get("operation_queue", {}).get("active", []),
    }

    return snapshot_data


@router.post("/push", summary="Push snapshot to HexaMonitor")
async def push_snapshot(
    request: Request,
    _token: str = Depends(verify_agent_key),
) -> dict[str, Any]:
    """
    Accepts the snapshot JSON from HexaAgent and stores it in memory.
    Requires a valid Bearer agent key.
    """
    global _LATEST_SNAPSHOT
    try:
        data = await request.json()
        _LATEST_SNAPSHOT = _merge_operations_into_snapshot(data)
        return {"status": "success", "message": "Snapshot cached successfully"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("", summary="Get unified HexaBeta production snapshot")
async def get_snapshot() -> dict[str, Any]:
    """
    Returns the latest cached snapshot to the dashboard.
    Falls back to local SnapshotManager if no external snapshot has been pushed.
    """
    global _LATEST_SNAPSHOT
    if _LATEST_SNAPSHOT:
        _LATEST_SNAPSHOT = _merge_operations_into_snapshot(_LATEST_SNAPSHOT)
        return _LATEST_SNAPSHOT

    try:
        from app.core.snapshot import snapshot_manager
        if snapshot_manager.snapshot:
            return snapshot_manager.snapshot
    except Exception:
        pass

    return {
        "status": "offline",
        "error": "No snapshot data received yet."
    }
