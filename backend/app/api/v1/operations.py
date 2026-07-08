import uuid
from datetime import datetime, timezone
from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Dict, Any

router = APIRouter()

_PENDING_OPERATIONS = []
_AUDIT_RECORDS = {}

class ValidateRequest(BaseModel):
    service: str
    operation: str

class ExecuteRequest(BaseModel):
    service: str
    operation: str
    token: str

def _clean_stale_operations():
    now = datetime.now(timezone.utc)
    for op_id, op in list(_AUDIT_RECORDS.items()):
        if op["status"] == "pending":
            started_at = op.get("timestamp")
            if started_at:
                diff = (now - started_at).total_seconds()
                if diff > 300:  # 5 minutes stale timeout
                    op["status"] = "failed"
                    op["error"] = "Operation timed out (stale request)"

@router.post("/validate")
async def validate_operation(payload: ValidateRequest):
    """
    Validates the operation. Since this is a simple proxy architecture,
    we simply return a token to allow the execute step to proceed.
    """
    return {
        "status": "valid",
        "token": str(uuid.uuid4())
    }

@router.post("/execute")
async def execute_operation(payload: ExecuteRequest):
    """
    Appends the operation to the queue for the agent to pull.
    """
    op_id = str(uuid.uuid4())
    op = {
        "id": op_id,
        "service": payload.service,
        "operation": payload.operation
    }
    _PENDING_OPERATIONS.append(op)
    
    # Register in audit records
    _AUDIT_RECORDS[op_id] = {
        "id": op_id,
        "service": payload.service,
        "operation": payload.operation,
        "status": "pending",
        "timestamp": datetime.now(timezone.utc)
    }
    
    return {
        "status": "queued",
        "operation_id": op_id
    }

@router.get("/pending")
async def get_pending_operations():
    """
    Called by HexaAgent to poll for operations.
    Returns all pending operations and clears the queue.
    """
    global _PENDING_OPERATIONS
    pending = list(_PENDING_OPERATIONS)
    _PENDING_OPERATIONS.clear()
    
    return {
        "operations": pending
    }

@router.get("/history")
async def get_operations_history():
    _clean_stale_operations()
    # Return sorted by timestamp desc
    records = list(_AUDIT_RECORDS.values())
    records.sort(key=lambda x: x["timestamp"], reverse=True)
    return {
        "status": "success",
        "operations": records
    }

@router.post("/{op_id}/cancel")
async def cancel_operation(op_id: str):
    _clean_stale_operations()
    if op_id not in _AUDIT_RECORDS:
        return {"status": "error", "message": "Operation not found."}
    
    op = _AUDIT_RECORDS[op_id]
    if op["status"] in ["success", "failed", "Cancelled"]:
        return {
            "status": "completed",
            "message": f"Operation already finished with status: {op['status']}."
        }
    
    # Still pending/running, cancel it
    op["status"] = "Cancelled"
    op["finished_at"] = datetime.now(timezone.utc)
    
    # Remove from pending queue if it's still there
    global _PENDING_OPERATIONS
    _PENDING_OPERATIONS = [p for p in _PENDING_OPERATIONS if p["id"] != op_id]
    
    # Queue a cancellation message for the agent
    cancel_op = {
        "id": str(uuid.uuid4()),
        "service": op["service"],
        "operation": "cancel",
        "target_op_id": op_id
    }
    _PENDING_OPERATIONS.append(cancel_op)
    
    return {
        "status": "cancelled",
        "message": "Operation cancelled successfully."
    }

@router.delete("/{op_id}")
async def delete_operation(op_id: str):
    if op_id not in _AUDIT_RECORDS:
        return {"status": "error", "message": "Operation not found."}
    
    op = _AUDIT_RECORDS[op_id]
    if op["status"] not in ["Cancelled", "failed"]:
        return {
            "status": "error",
            "message": "Only cancelled or failed operations can be deleted."
        }
    
    del _AUDIT_RECORDS[op_id]
    return {
        "status": "success",
        "message": "Operation deleted from history."
    }
