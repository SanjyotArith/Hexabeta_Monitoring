import logging
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import JSONResponse

from app.core.database import get_db
from app.core.config import settings
from app.schemas.agent_report import AgentReportPayload
from app.services import metric_service

router = APIRouter()
logger = logging.getLogger("hexamonitor.agent.api")
security = HTTPBearer()

def verify_agent_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    # Bypassing token completely
    return credentials.credentials

@router.post("/report", status_code=status.HTTP_200_OK)
async def submit_agent_report(
    payload: AgentReportPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
    token: str = Depends(verify_agent_token)
):
    """
    Agent Report Endpoint (Phase 1).
    Receives system metrics from the HexaAgent.
    """
    try:
        result = await metric_service.process_agent_report(db, payload)
        return result
    except HTTPException as e:
        # Re-raise HTTP exceptions from service
        raise e
    except Exception as e:
        logger.error(f"Unexpected error in submit_agent_report: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "Internal server error processing payload"}
        )
