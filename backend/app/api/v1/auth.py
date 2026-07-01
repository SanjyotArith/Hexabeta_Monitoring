from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func

from app.core.database import get_db
from app.core.security import verify_password, get_password_hash, create_access_token, create_refresh_token, decode_token
from app.models.users import User, Session
from app.schemas.auth import UserCreate, UserResponse, LoginRequest, TokenResponse
from app.api.deps import get_current_user

router = APIRouter()

@router.post("/register", response_model=UserResponse)
async def register(user_in: UserCreate, db: AsyncSession = Depends(get_db)):
    """
    Registers the initial Administrator user.
    To prevent unauthorized access, registration is blocked if an admin already exists in the system.
    """
    # Count existing users in database
    user_count_result = await db.execute(select(func.count(User.id)))
    user_count = user_count_result.scalar()
    
    if user_count > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Registration is disabled. An administrator account already exists."
        )
        
    # Check if user already exists with the same username or email (fallback)
    result = await db.execute(
        select(User).where((User.username == user_in.username) | (User.email == user_in.email))
    )
    if result.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username or email already registered."
        )
        
    hashed_password = get_password_hash(user_in.password)
    new_user = User(
        username=user_in.username,
        email=user_in.email,
        password_hash=hashed_password,
        is_active=True
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return new_user


@router.post("/login", response_model=TokenResponse)
async def login(
    login_in: LoginRequest,
    response: Response,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Authenticates the Administrator and returns an access token.
    Stores the refresh token in an HttpOnly secure cookie for sliding sessions.
    """
    # Check user lookup
    result = await db.execute(
        select(User).where((User.username == login_in.username) | (User.email == login_in.username))
    )
    user = result.scalars().first()
    
    if not user or not verify_password(login_in.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username/email or password"
        )
        
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Account is inactive"
        )
        
    # Generate tokens
    access_token = create_access_token(subject=user.username)
    refresh_token = create_refresh_token(subject=user.username)
    
    # Save refresh token session in database
    expires_at = datetime.utcnow() + timedelta(days=7)
    session = Session(
        user_id=user.id,
        refresh_token=refresh_token,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
        expires_at=expires_at
    )
    db.add(session)
    await db.commit()
    
    # Set sliding refresh session cookie
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="lax",
        expires=expires_at.replace(tzinfo=timezone.utc)
    )
    
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Refreshes the access token using the stored refresh token cookie.
    """
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token missing"
        )
        
    payload = decode_token(refresh_token)
    if payload is None or payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )
        
    # Check if session exists in DB and is not expired
    result = await db.execute(select(Session).where(Session.refresh_token == refresh_token))
    session = result.scalars().first()
    
    if not session or session.expires_at.replace(tzinfo=None) < datetime.utcnow():
        if session:
            await db.delete(session)
            await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid"
        )
        
    # Fetch admin user
    user_result = await db.execute(select(User).where(User.id == session.user_id))
    user = user_result.scalars().first()
    
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive"
        )
        
    # Return new access token
    new_access_token = create_access_token(subject=user.username)
    return {"access_token": new_access_token, "token_type": "bearer"}


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db)
):
    """
    Logs out the Administrator and invalidates the session in the database.
    """
    refresh_token = request.cookies.get("refresh_token")
    if refresh_token:
        result = await db.execute(select(Session).where(Session.refresh_token == refresh_token))
        session = result.scalars().first()
        if session:
            await db.delete(session)
            await db.commit()
            
    response.delete_cookie(key="refresh_token")
    return {"detail": "Successfully logged out"}


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """
    Retrieves the profile of the current logged-in Administrator.
    """
    return current_user
