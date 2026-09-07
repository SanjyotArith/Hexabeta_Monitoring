"""
Tests for HexaMonitor snapshot push endpoint authentication.

Verifies that POST /api/v1/snapshot/push correctly enforces
Bearer token authentication using the configured AGENT_KEY.
"""

import os
import pytest
from unittest.mock import patch
from httpx import AsyncClient, ASGITransport

# Set a known test agent key BEFORE importing the app so config picks it up
TEST_AGENT_KEY = "test-agent-key-for-unit-tests"
os.environ["AGENT_KEY"] = TEST_AGENT_KEY

from app.main import app  # noqa: E402

SNAPSHOT_PUSH_URL = "/api/v1/snapshot/push"
SNAPSHOT_GET_URL = "/api/v1/snapshot"

SAMPLE_SNAPSHOT = {
    "success": True,
    "timestamp": "2026-09-07T12:00:00Z",
    "infrastructure": {"cpu": {"usage_percent": 15.2}},
}


@pytest.fixture
def transport():
    return ASGITransport(app=app)


@pytest.mark.asyncio
async def test_push_without_auth_returns_401(transport):
    """POST without Authorization header must be rejected."""
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(SNAPSHOT_PUSH_URL, json=SAMPLE_SNAPSHOT)
    assert response.status_code == 401  # verify_agent_key returns 401 when header is missing


@pytest.mark.asyncio
async def test_push_with_invalid_token_returns_401(transport):
    """POST with an incorrect Bearer token must be rejected."""
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            SNAPSHOT_PUSH_URL,
            json=SAMPLE_SNAPSHOT,
            headers={"Authorization": "Bearer wrong-key-entirely"},
        )
    assert response.status_code == 401
    assert "Invalid agent key" in response.json().get("detail", "")


@pytest.mark.asyncio
async def test_push_with_valid_token_succeeds(transport):
    """POST with the correct Bearer token must be accepted."""
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            SNAPSHOT_PUSH_URL,
            json=SAMPLE_SNAPSHOT,
            headers={"Authorization": f"Bearer {TEST_AGENT_KEY}"},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"


@pytest.mark.asyncio
async def test_push_snapshot_data_is_cached(transport):
    """After a valid push, the GET endpoint should return the pushed data."""
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Push a snapshot
        push_response = await client.post(
            SNAPSHOT_PUSH_URL,
            json=SAMPLE_SNAPSHOT,
            headers={"Authorization": f"Bearer {TEST_AGENT_KEY}"},
        )
        assert push_response.status_code == 200

        # Retrieve and verify
        get_response = await client.get(SNAPSHOT_GET_URL)
        assert get_response.status_code == 200
        cached = get_response.json()
        assert cached.get("success") is True
        assert cached.get("timestamp") == SAMPLE_SNAPSHOT["timestamp"]


@pytest.mark.asyncio
async def test_get_snapshot_does_not_require_auth(transport):
    """GET /api/v1/snapshot should remain publicly accessible (dashboard reads)."""
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(SNAPSHOT_GET_URL)
    # Should not be 401/403 — it's either 200 with data or 200 with "offline" status
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_auth_uses_configured_agent_key(transport):
    """Verify the dependency checks against the settings AGENT_KEY value."""
    from app.core.config import settings

    # The test env sets AGENT_KEY = TEST_AGENT_KEY
    # A request using settings.AGENT_KEY must succeed
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            SNAPSHOT_PUSH_URL,
            json=SAMPLE_SNAPSHOT,
            headers={"Authorization": f"Bearer {settings.AGENT_KEY}"},
        )
    assert response.status_code == 200
