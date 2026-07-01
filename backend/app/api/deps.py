from fastapi import Depends, HTTPException, status, Header
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import hashlib

from app.core.database import get_db
from app.core.security import decode_token
from app.models.users import User
from app.models.infrastructure import Agent

# Standard OAuth2 scheme mapping to the login route
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db)
) -> User:
    """FastAPI Dependency to retrieve the currently authenticated Admin user."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    payload = decode_token(token)
    if payload is None or payload.get("type") != "access":
        raise credentials_exception
        
    username: str = payload.get("sub")
    if username is None:
        raise credentials_exception
        
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalars().first()
    if user is None or not user.is_active:
        raise credentials_exception
        
    return user


async def get_current_agent(
    x_agent_token: str = Header(..., alias="X-Agent-Token"),
    db: AsyncSession = Depends(get_db)
) -> Agent:
    """FastAPI Dependency to validate HexaAgent telemetry using SHA-256 tokens."""
    token_hash = hashlib.sha256(x_agent_token.encode()).hexdigest()
    
    result = await db.execute(select(Agent).where(Agent.token_hash == token_hash))
    agent = result.scalars().first()
    
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive agent token"
        )
        
    return agent
