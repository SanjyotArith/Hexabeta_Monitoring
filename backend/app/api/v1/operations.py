"""
HexaAgent — Operations API Router (v1).

Exposes operations listing, confirmation flow, validation pre-flight,
execution queuing, cancellation, and audit log history.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.operations import (
    COMMANDS_REGISTRY,
    ValidationEngine,
    audit_logger,
    confirmation_manager,
    queue_manager,
)

logger = logging.getLogger("hexa_agent.api.v1.operations")

router = APIRouter(prefix="/operations", tags=["Operations"])


# --- Security Token Dependency ---
def verify_operation_token(x_operation_token: str = Header(...)) -> str:
    """Validate that the request header contains the correct operation token."""
    settings = get_settings()
    if x_operation_token != settings.OPERATION_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Invalid operation token",
        )
    return x_operation_token


# --- Pydantic Schemas for Requests ---
class ValidationRequest(BaseModel):
    service: str = Field(..., description="Service name (e.g. backend, postgres, redis, nginx, cloudflared, deploy)")
    operation: str = Field(..., description="Action to perform (e.g. start, stop, restart, execute, dry_run)")


class ConfirmationRequest(BaseModel):
    service: str = Field(...)
    operation: str = Field(...)
    mode: str = Field("production", description="Execution mode: production or dry_run")


class ExecutionRequest(BaseModel):
    confirmation_token: str = Field(..., description="The temporary confirmation token returned from /confirm")
    phrase: str = Field(..., description="Verification phrase (must be RESTART or DEPLOY)")


class CancelRequest(BaseModel):
    operation_id: str = Field(..., description="ID of the pending operation to cancel")


# --- Endpoint Route Handlers ---

@router.get(
    "",
    summary="Get all supported production operations",
    description="Returns a list of all operations configured in the registry.",
)
async def list_operations() -> dict[str, Any]:
    """Return the configuration-driven commands registry."""
    return {
        "success": True,
        "services": list(COMMANDS_REGISTRY.keys()),
        "registry": COMMANDS_REGISTRY,
    }


@router.get(
    "/history",
    summary="Get audit log history",
    description="Returns the execution logs of all completed, failed, or running operations.",
)
async def get_audit_history(limit: int = 50) -> dict[str, Any]:
    """Query audit logs list from database."""
    history = audit_logger.get_history(limit=limit)
    return {
        "success": True,
        "history": history,
        "count": len(history),
    }


@router.post(
    "/validate",
    summary="Pre-flight validation for an operation",
    description="Validates if command executables, plists, or scripts are present and ready.",
    dependencies=[Depends(verify_operation_token)],
)
async def validate_operation(payload: ValidationRequest) -> dict[str, Any]:
    """Perform pre-flight checks on service or script paths."""
    is_valid, errors = ValidationEngine.validate(payload.service, payload.operation)
    return {
        "success": is_valid,
        "service": payload.service,
        "operation": payload.operation,
        "valid": is_valid,
        "errors": errors,
    }


@router.post(
    "/confirm",
    summary="Step 1: Initiate Double-Confirmation Session",
    description="Validates operation first, then generates a temporary token and phrase for the frontend confirmation prompt.",
    dependencies=[Depends(verify_operation_token)],
)
async def initiate_confirmation(payload: ConfirmationRequest) -> dict[str, Any]:
    """Validate checks first, then issue short-lived token requiring verification input."""
    # Pre-validate
    is_valid, errors = ValidationEngine.validate(payload.service, payload.operation)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Pre-flight validation failed: {'; '.join(errors)}",
        )

    # Issue token
    token = confirmation_manager.generate_token(
        payload.service, payload.operation, payload.mode
    )
    
    phrase = "DEPLOY" if payload.service == "deploy" else "RESTART"
    warning = (
        "This operation will disrupt active user connections. Please confirm."
        if phrase == "RESTART"
        else "This will pull, build, restart services, and verify the build. Please confirm."
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


@router.post(
    "/execute",
    summary="Step 2: Submit Confirmed Operation to Queue",
    description="Validates confirmation token and matching phrase, then places the task in the execution queue.",
    dependencies=[Depends(verify_operation_token)],
)
async def execute_confirmed_operation(payload: ExecutionRequest) -> dict[str, Any]:
    """Claim confirmation token and schedule operation task in queue."""
    session = confirmation_manager.verify_and_claim(
        payload.confirmation_token, payload.phrase
    )
    if not session:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid, expired, or incorrect confirmation credentials.",
        )

    # Submit to sequential background worker queue
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


@router.post(
    "/cancel",
    summary="Cancel a queued operation",
    description="Cancels a pending task in the queue if it has not started running yet.",
    dependencies=[Depends(verify_operation_token)],
)
async def cancel_operation(payload: CancelRequest) -> dict[str, Any]:
    """Attempt cancellation of a queued task."""
    cancelled = queue_manager.cancel_operation(payload.operation_id)
    if not cancelled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Operation could not be cancelled (either not found or already running/completed).",
        )
    return {
        "success": True,
        "message": f"Successfully cancelled operation {payload.operation_id}",
    }
