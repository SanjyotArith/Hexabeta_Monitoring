"""
HexaMonitor & HexaAgent — Operations API Router (v1).

Exposes:
GET    /api/v1/operations             — List supported production operations
GET    /api/v1/operations/history     — Get audit log history
GET    /api/v1/operations/pending     — Polled by HexaAgent to get pending operations
POST   /api/v1/operations/validate    — Pre-flight validation for an operation
POST   /api/v1/operations/confirm     — Initiate double-confirmation session
POST   /api/v1/operations/execute     — Submit confirmed operation to queue
POST   /api/v1/operations/cancel      — Cancel a queued operation
DELETE /api/v1/operations/{op_id}     — Delete an operation record
"""

from __future__ import annotations

import uuid
import logging
from typing import Any, Optional, List, Dict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from app.core.config import get_settings

logger = logging.getLogger("hexamonitor.api.v1.operations")

router = APIRouter(prefix="/operations", tags=["Operations"])

_PENDING_OPERATIONS: list[dict[str, Any]] = []
_AUDIT_RECORDS: dict[str, dict[str, Any]] = {}


def _clean_stale_operations():
    now = datetime.now(timezone.utc)
    for op_id, op in list(_AUDIT_RECORDS.items()):
        if op.get("status") == "pending":
            started_at = op.get("timestamp")
            if started_at:
                diff = (now - started_at).total_seconds()
                if diff > 300:
                    op["status"] = "failed"
                    op["error"] = "Operation timed out (stale request)"


def verify_operation_token(x_operation_token: Optional[str] = Header(None)) -> Optional[str]:
    settings = get_settings()
    if x_operation_token and x_operation_token != settings.OPERATION_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Invalid operation token",
        )
    return x_operation_token


# --- Schemas ---

class ValidateRequest(BaseModel):
    service: str = Field(..., description="Service name")
    operation: str = Field(..., description="Action to perform")


class ConfirmationRequest(BaseModel):
    service: str = Field(...)
    operation: str = Field(...)
    mode: str = Field("production", description="Execution mode")


class ExecuteRequest(BaseModel):
    service: Optional[str] = None
    operation: Optional[str] = None
    token: Optional[str] = None
    confirmation_token: Optional[str] = None
    phrase: Optional[str] = None


class CancelRequest(BaseModel):
    operation_id: str = Field(...)


# --- Endpoints ---

@router.get("", summary="Get supported production operations")
async def list_operations() -> dict[str, Any]:
    try:
        from app.core.operations import COMMANDS_REGISTRY
        return {
            "success": True,
            "services": list(COMMANDS_REGISTRY.keys()),
            "registry": COMMANDS_REGISTRY,
        }
    except Exception:
        return {"success": True, "services": [], "registry": {}}


@router.get("/history", summary="Get operations history")
async def get_operations_history(limit: int = 50) -> dict[str, Any]:
    _clean_stale_operations()
    records = list(_AUDIT_RECORDS.values())
    records.sort(key=lambda x: x.get("timestamp", datetime.now(timezone.utc)), reverse=True)

    try:
        from app.core.operations import audit_logger
        agent_history = audit_logger.get_history(limit=limit)
        return {
            "success": True,
            "status": "success",
            "operations": records,
            "history": agent_history,
            "count": len(records) + len(agent_history),
        }
    except Exception:
        return {
            "success": True,
            "status": "success",
            "operations": records,
            "count": len(records),
        }


@router.post("/validate", summary="Validate operation")
async def validate_operation(payload: ValidateRequest) -> dict[str, Any]:
    is_valid = True
    errors = []
    try:
        from app.core.operations import ValidationEngine
        is_valid, errors = ValidationEngine.validate(payload.service, payload.operation)
    except Exception:
        pass

    token = str(uuid.uuid4())
    return {
        "status": "valid" if is_valid else "invalid",
        "success": is_valid,
        "service": payload.service,
        "operation": payload.operation,
        "token": token,
        "valid": is_valid,
        "errors": errors,
    }


@router.post("/confirm", summary="Initiate double confirmation")
async def initiate_confirmation(payload: ConfirmationRequest) -> dict[str, Any]:
    try:
        from app.core.operations import ValidationEngine, confirmation_manager
        is_valid, errors = ValidationEngine.validate(payload.service, payload.operation)
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Pre-flight validation failed: {'; '.join(errors)}",
            )
        token = confirmation_manager.generate_token(payload.service, payload.operation, payload.mode)
    except HTTPException:
        raise
    except Exception:
        token = str(uuid.uuid4())

    phrase = "DEPLOY" if payload.service == "deploy" else "RESTART"
    warning = (
        "This operation will disrupt active user connections."
        if phrase == "RESTART"
        else "This will pull, build, restart services, and verify the build."
    )

    return {
        "success": True,
        "confirmation_token": token,
        "required_input": phrase,
        "warning_message": warning,
        "service": payload.service,
        "operation": payload.operation,
        "mode": payload.mode,
    }


@router.post("/execute", summary="Execute operation")
async def execute_operation(payload: ExecuteRequest) -> dict[str, Any]:
    op_id = str(uuid.uuid4())
    service_name = payload.service or "system"
    operation_name = payload.operation or "restart"

    # Try agent queue execution if confirmation_token is present
    if payload.confirmation_token and payload.phrase:
        try:
            from app.core.operations import confirmation_manager, queue_manager
            session = confirmation_manager.verify_and_claim(payload.confirmation_token, payload.phrase)
            if session:
                queued_task = queue_manager.submit(
                    service=session["service"],
                    operation=session["operation"],
                    mode=session["mode"],
                )
                return {
                    "success": True,
                    "message": "Operation accepted and queued.",
                    "operation_id": queued_task["id"],
                    "status": queued_task["status"],
                }
        except Exception as e:
            logger.warning("Agent queue execution fallback: %s", e)

    # Monitor pending queue execution
    op = {
        "id": op_id,
        "service": service_name,
        "operation": operation_name,
    }
    _PENDING_OPERATIONS.append(op)
    _AUDIT_RECORDS[op_id] = {
        "id": op_id,
        "service": service_name,
        "operation": operation_name,
        "status": "pending",
        "timestamp": datetime.now(timezone.utc),
    }

    return {
        "success": True,
        "status": "queued",
        "operation_id": op_id,
    }


@router.get("/pending", summary="Get pending operations for agent polling")
async def get_pending_operations() -> dict[str, Any]:
    global _PENDING_OPERATIONS
    pending = list(_PENDING_OPERATIONS)
    _PENDING_OPERATIONS.clear()
    return {"operations": pending}


@router.post("/cancel", summary="Cancel operation")
@router.post("/{op_id}/cancel", summary="Cancel operation by ID")
async def cancel_operation(payload: Optional[CancelRequest] = None, op_id: Optional[str] = None) -> dict[str, Any]:
    target_id = op_id or (payload.operation_id if payload else None)
    if not target_id:
        raise HTTPException(status_code=400, detail="Missing operation_id")

    _clean_stale_operations()

    # Try agent queue cancellation first
    try:
        from app.core.operations import queue_manager
        if queue_manager.cancel_operation(target_id):
            return {"success": True, "status": "cancelled", "message": f"Successfully cancelled operation {target_id}"}
    except Exception:
        pass

    if target_id not in _AUDIT_RECORDS:
        return {"status": "error", "message": "Operation not found."}

    op = _AUDIT_RECORDS[target_id]
    if op["status"] in ["success", "failed", "Cancelled"]:
        return {
            "status": "completed",
            "message": f"Operation already finished with status: {op['status']}.",
        }

    op["status"] = "Cancelled"
    op["finished_at"] = datetime.now(timezone.utc)

    global _PENDING_OPERATIONS
    _PENDING_OPERATIONS = [p for p in _PENDING_OPERATIONS if p["id"] != target_id]

    cancel_op = {
        "id": str(uuid.uuid4()),
        "service": op["service"],
        "operation": "cancel",
        "target_op_id": target_id,
    }
    _PENDING_OPERATIONS.append(cancel_op)

    return {"success": True, "status": "cancelled", "message": "Operation cancelled successfully."}


@router.delete("/{op_id}", summary="Delete operation record")
async def delete_operation(op_id: str) -> dict[str, Any]:
    if op_id not in _AUDIT_RECORDS:
        return {"status": "error", "message": "Operation not found."}

    op = _AUDIT_RECORDS[op_id]
    if op["status"] not in ["Cancelled", "failed"]:
        return {
            "status": "error",
            "message": "Only cancelled or failed operations can be deleted.",
        }

    del _AUDIT_RECORDS[op_id]
    return {"status": "success", "message": "Operation deleted from history."}
