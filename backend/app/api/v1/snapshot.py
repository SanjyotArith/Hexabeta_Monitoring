from fastapi import APIRouter, Request
from app.api.v1.operations import _AUDIT_RECORDS, _clean_stale_operations

router = APIRouter()

# Simple in-memory cache for the latest snapshot
_LATEST_SNAPSHOT = {}

def _merge_operations_into_snapshot(snapshot_data):
    if not snapshot_data:
        return snapshot_data
        
    _clean_stale_operations()
    
    # Sort audit records to find the latest
    records = list(_AUDIT_RECORDS.values())
    
    if records:
        records.sort(key=lambda x: x["timestamp"], reverse=True)
        latest_record = records[0]
        
        # Override or sync the latest audit record
        agent_audit = snapshot_data.get("latest_audit_record")
        if agent_audit:
            # The agent might send 'id' or just service/operation
            op_id = agent_audit.get("id")
            if op_id and op_id in _AUDIT_RECORDS:
                if _AUDIT_RECORDS[op_id]["status"] in ["pending", "running"]:
                    new_status = agent_audit.get("status")
                    if new_status in ["success", "failed", "running"]:
                        _AUDIT_RECORDS[op_id]["status"] = new_status
                        if new_status in ["success", "failed"]:
                            _AUDIT_RECORDS[op_id]["finished_at"] = datetime.now(timezone.utc)
            else:
                # Fallback if no ID is provided, try to match by service and operation
                for rec in _AUDIT_RECORDS.values():
                    if rec["status"] in ["pending", "running"] and agent_audit.get("service") == rec["service"] and agent_audit.get("operation") == rec["operation"]:
                        new_status = agent_audit.get("status")
                        if new_status in ["success", "failed", "running"]:
                            rec["status"] = new_status
                            if new_status in ["success", "failed"]:
                                rec["finished_at"] = datetime.now(timezone.utc)
                        break
                    
        # Update snapshot to reflect the actual latest backend record state
        snapshot_data["latest_audit_record"] = {
            "id": latest_record["id"],
            "service": latest_record["service"],
            "operation": latest_record["operation"],
            "status": latest_record["status"]
        }
    else:
        # If no audit records in backend, remove it
        if "latest_audit_record" in snapshot_data:
            del snapshot_data["latest_audit_record"]
            
    # Sync the operation queue
    pending_ops = [op for op in _AUDIT_RECORDS.values() if op["status"] == "pending"]
    snapshot_data["operation_queue"] = {
        "pending": [{"id": op["id"], "service": op["service"], "operation": op["operation"]} for op in pending_ops],
        "pending_count": len(pending_ops),
        "active": snapshot_data.get("operation_queue", {}).get("active", [])
    }
    
    return snapshot_data

@router.post("/push")
async def push_snapshot(request: Request):
    """
    Accepts the snapshot JSON from HexaAgent and stores it in memory.
    """
    global _LATEST_SNAPSHOT
    try:
        data = await request.json()
        _LATEST_SNAPSHOT = _merge_operations_into_snapshot(data)
        return {"status": "success", "message": "Snapshot cached successfully"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.get("")
async def get_snapshot():
    """
    Returns the latest cached snapshot to the dashboard.
    """
    global _LATEST_SNAPSHOT
    if not _LATEST_SNAPSHOT:
        return {
            "status": "offline",
            "error": "No snapshot data received yet."
        }
    # Update local operations state before returning
    _LATEST_SNAPSHOT = _merge_operations_into_snapshot(_LATEST_SNAPSHOT)
    return _LATEST_SNAPSHOT
