"""
Tests for HexaMonitor Authentication and Authorization.

Validates:
1. Nonexistent user -> 401 Unauthorized (instead of 500).
2. Invalid password -> 401 Unauthorized.
3. Valid credentials -> 200 OK with access token and session record.
4. Inactive user account -> 403 Forbidden.
5. Approval status and role properties on User model.
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.core.database import SessionLocal, engine
from app.core.security import get_password_hash
from app.models.users import User, Session
from sqlalchemy.future import select

AUTH_LOGIN_URL = "/api/v1/auth/login"


@pytest_asyncio.fixture(autouse=True)
async def cleanup_engine():
    yield
    await engine.dispose()


@pytest.fixture
def transport():
    return ASGITransport(app=app)


@pytest.mark.asyncio
async def test_login_nonexistent_user_returns_401(transport):
    """POST /api/v1/auth/login with non-existent user returns 401 Unauthorized."""
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            AUTH_LOGIN_URL,
            json={"username": "definitely_nonexistent_user_12345", "password": "Password123!"}
        )
    assert res.status_code == 401
    assert res.json()["detail"] == "Incorrect username/email or password"


@pytest.mark.asyncio
async def test_login_invalid_password_returns_401(transport):
    """POST /api/v1/auth/login with valid user but wrong password returns 401 Unauthorized."""
    async with SessionLocal() as db:
        user = User(
            username="auth_test_user_wrong_pw",
            email="auth_wrong_pw@example.com",
            password_hash=get_password_hash("CorrectPassword123!"),
            is_active=True,
        )
        db.add(user)
        await db.commit()
        user_id = user.id

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.post(
                AUTH_LOGIN_URL,
                json={"username": "auth_test_user_wrong_pw", "password": "WrongPassword!"}
            )
        assert res.status_code == 401
        assert res.json()["detail"] == "Incorrect username/email or password"
    finally:
        async with SessionLocal() as db:
            res = await db.execute(select(User).where(User.id == user_id))
            u = res.scalars().first()
            if u:
                await db.delete(u)
                await db.commit()


@pytest.mark.asyncio
async def test_login_success_creates_session(transport):
    """POST /api/v1/auth/login with valid credentials returns 200, access token, and creates a Session."""
    password = "ValidPassword123!"
    async with SessionLocal() as db:
        user = User(
            username="auth_test_valid_user",
            email="auth_valid@example.com",
            password_hash=get_password_hash(password),
            is_active=True,
        )
        db.add(user)
        await db.commit()
        user_id = user.id

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.post(
                AUTH_LOGIN_URL,
                json={"username": "auth_test_valid_user", "password": password}
            )
        assert res.status_code == 200
        data = res.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

        # Check refresh_token cookie set
        assert "refresh_token" in res.cookies

        # Verify Session record created in database
        async with SessionLocal() as db:
            result = await db.execute(select(Session).where(Session.user_id == user_id))
            sessions = result.scalars().all()
            assert len(sessions) >= 1
            assert sessions[0].refresh_token == res.cookies["refresh_token"]

            for s in sessions:
                await db.delete(s)
            await db.commit()
    finally:
        async with SessionLocal() as db:
            res = await db.execute(select(User).where(User.id == user_id))
            u = res.scalars().first()
            if u:
                await db.delete(u)
                await db.commit()


@pytest.mark.asyncio
async def test_login_inactive_user_returns_403(transport):
    """POST /api/v1/auth/login with inactive user account returns 403 Forbidden."""
    password = "ValidPassword123!"
    async with SessionLocal() as db:
        user = User(
            username="auth_test_inactive_user",
            email="auth_inactive@example.com",
            password_hash=get_password_hash(password),
            is_active=False,
        )
        db.add(user)
        await db.commit()
        user_id = user.id

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.post(
                AUTH_LOGIN_URL,
                json={"username": "auth_test_inactive_user", "password": password}
            )
        assert res.status_code == 403
        assert "disabled" in res.json()["detail"].lower()
    finally:
        async with SessionLocal() as db:
            res = await db.execute(select(User).where(User.id == user_id))
            u = res.scalars().first()
            if u:
                await db.delete(u)
                await db.commit()


def test_user_properties_compatibility():
    """Verify User model fallback properties (role, approval_status, full_name) work without DB errors."""
    user = User(username="test_prop", email="test_prop@example.com", is_active=True)
    assert user.role == "admin"
    assert user.approval_status == "approved"
    assert user.full_name is None

    user.role = "user"
    user.approval_status = "pending"
    user.full_name = "Test User"
    assert user.role == "user"
    assert user.approval_status == "pending"
    assert user.full_name == "Test User"
