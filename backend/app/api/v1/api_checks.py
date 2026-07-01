from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.database import get_db
from app.models.telemetry import ApiCheck, ApiCheckHistory
from app.models.infrastructure import Environment
from app.schemas.api_checks import ApiCheckCreate, ApiCheckResponse, ApiCheckUpdate, ApiCheckHistoryResponse
from app.api.deps import get_current_user
from app.models.users import User

router = APIRouter()

@router.get("/environments/{env_id}", response_model=List[ApiCheckResponse])
async def list_api_checks(
    env_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lists all synthetic API check configurations within an environment."""
    # Verify environment
    env_result = await db.execute(select(Environment).where(Environment.id == env_id))
    if not env_result.scalars().first():
        raise HTTPException(status_code=404, detail="Environment not found")
        
    result = await db.execute(select(ApiCheck).where(ApiCheck.environment_id == env_id))
    return result.scalars().all()


@router.post("/environments/{env_id}", response_model=ApiCheckResponse, status_code=status.HTTP_201_CREATED)
async def create_api_check(
    env_id: int,
    check_in: ApiCheckCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Creates a new synthetic API check configuration within an environment."""
    # Verify environment
    env_result = await db.execute(select(Environment).where(Environment.id == env_id))
    if not env_result.scalars().first():
        raise HTTPException(status_code=404, detail="Environment not found")
        
    new_check = ApiCheck(
        environment_id=env_id,
        **check_in.model_dump()
    )
    db.add(new_check)
    await db.commit()
    await db.refresh(new_check)
    return new_check


@router.put("/{id}", response_model=ApiCheckResponse)
async def update_api_check(
    id: int,
    check_in: ApiCheckUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Updates an existing API check configuration."""
    result = await db.execute(select(ApiCheck).where(ApiCheck.id == id))
    api_check = result.scalars().first()
    if not api_check:
        raise HTTPException(status_code=404, detail="API Check configuration not found")
        
    update_data = check_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(api_check, field, value)
        
    await db.commit()
    await db.refresh(api_check)
    return api_check


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_check(
    id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Deletes an API check configuration and all its associated historical entries."""
    result = await db.execute(select(ApiCheck).where(ApiCheck.id == id))
    api_check = result.scalars().first()
    if not api_check:
        raise HTTPException(status_code=404, detail="API Check configuration not found")
        
    await db.delete(api_check)
    await db.commit()
    return


@router.get("/{id}/history", response_model=List[ApiCheckHistoryResponse])
async def get_api_check_history(
    id: int,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retrieves the execution latency and uptime history for a specific API check."""
    # Verify check
    result = await db.execute(select(ApiCheck).where(ApiCheck.id == id))
    if not result.scalars().first():
        raise HTTPException(status_code=404, detail="API Check not found")
        
    history_result = await db.execute(
        select(ApiCheckHistory)
        .where(ApiCheckHistory.api_check_id == id)
        .order_by(ApiCheckHistory.timestamp.desc())
        .limit(limit)
    )
    return history_result.scalars().all()
