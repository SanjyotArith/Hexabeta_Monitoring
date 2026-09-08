"""
Tests for HexaMonitor Agent Report Endpoint and Schema Validation.

Proves:
1. Complete GPU report -> accepted.
2. GPU fields set to null -> accepted (e.g. GCP/Linux Agents).
3. Missing unrelated required report fields -> rejected (422).
4. Invalid unrelated field types -> rejected (422).
5. Existing authentication/authorization behavior remains unchanged.
"""

import pytest
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport
from pydantic import ValidationError

from app.main import app
from app.schemas.agent_report import AgentReportPayload, GPUReport, SystemMetrics

AGENT_REPORT_URL = "/api/v1/agents/report"

VALID_COMPLETE_REPORT = {
    "machine_information": {"name": "mac-mini-m2"},
    "project": "Hexa-Core",
    "environment": "Production",
    "timestamp": "2026-09-08T10:00:00Z",
    "agent_version": "1.0.0",
    "system_metrics": {
        "cpu": {"cpu_percent": 14.5},
        "memory": {
            "memory_bytes": 17179869184,
            "memory_mb": 16384.0,
            "memory_gb": 16.0
        },
        "storage": {
            "project_bytes": 5000000,
            "project_mb": 5.0,
            "project_gb": 0.005,
            "backend_bytes": 3000000,
            "backend_mb": 3.0,
            "backend_gb": 0.003,
            "frontend_bytes": 1000000,
            "frontend_mb": 1.0,
            "frontend_gb": 0.001,
            "uploads_bytes": 1000000,
            "uploads_mb": 1.0,
            "uploads_gb": 0.001
        },
        "gpu": {
            "model": "Apple M2 Max",
            "vendor": "Apple",
            "core_count": 38,
            "metal_supported": True,
            "metal_family": "metal3",
            "utilization": 22.5
        }
    }
}

VALID_NULL_GPU_REPORT = {
    "machine_information": {"name": "gcp-linux-instance-1"},
    "project": "Hexa-Core",
    "environment": "Production",
    "timestamp": "2026-09-08T10:00:00Z",
    "agent_version": "1.0.0",
    "system_metrics": {
        "cpu": {"cpu_percent": 8.2},
        "memory": {
            "memory_bytes": 8589934592,
            "memory_mb": 8192.0,
            "memory_gb": 8.0
        },
        "storage": {
            "project_bytes": 5000000,
            "project_mb": 5.0,
            "project_gb": 0.005,
            "backend_bytes": 3000000,
            "backend_mb": 3.0,
            "backend_gb": 0.003,
            "frontend_bytes": 1000000,
            "frontend_mb": 1.0,
            "frontend_gb": 0.001,
            "uploads_bytes": 1000000,
            "uploads_mb": 1.0,
            "uploads_gb": 0.001
        },
        "gpu": {
            "model": None,
            "vendor": None,
            "core_count": None,
            "metal_supported": None,
            "metal_family": None,
            "utilization": None
        }
    }
}

VALID_NONE_GPU_OBJECT_REPORT = {
    "machine_information": {"name": "headless-server"},
    "project": "Hexa-Core",
    "environment": "Staging",
    "timestamp": "2026-09-08T10:00:00Z",
    "agent_version": "1.0.0",
    "system_metrics": {
        "cpu": {"cpu_percent": 5.0},
        "memory": {
            "memory_bytes": 4294967296,
            "memory_mb": 4096.0,
            "memory_gb": 4.0
        },
        "storage": {
            "project_bytes": 0, "project_mb": 0.0, "project_gb": 0.0,
            "backend_bytes": 0, "backend_mb": 0.0, "backend_gb": 0.0,
            "frontend_bytes": 0, "frontend_mb": 0.0, "frontend_gb": 0.0,
            "uploads_bytes": 0, "uploads_mb": 0.0, "uploads_gb": 0.0
        },
        "gpu": None
    }
}


@pytest.fixture
def transport():
    return ASGITransport(app=app)


# ------------------------------------------------------------------
# Test 1: Complete GPU report -> accepted
# ------------------------------------------------------------------
def test_schema_complete_gpu_report():
    """Pydantic model must validate a report with complete GPU info."""
    payload = AgentReportPayload(**VALID_COMPLETE_REPORT)
    assert payload.system_metrics.gpu is not None
    assert payload.system_metrics.gpu.model == "Apple M2 Max"
    assert payload.system_metrics.gpu.vendor == "Apple"
    assert payload.system_metrics.gpu.core_count == 38
    assert payload.system_metrics.gpu.metal_supported is True
    assert payload.system_metrics.gpu.metal_family == "metal3"
    assert payload.system_metrics.gpu.utilization == 22.5


@pytest.mark.asyncio
async def test_endpoint_complete_gpu_report_accepted(transport):
    """POST /api/v1/agents/report accepts complete GPU reports with HTTP 200."""
    with patch("app.api.v1.agents.metric_service.process_agent_report", new_callable=AsyncMock) as mock_process:
        mock_process.return_value = {"status": "success", "message": "Metrics processed successfully"}
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.post(
                AGENT_REPORT_URL,
                json=VALID_COMPLETE_REPORT,
                headers={"Authorization": "Bearer test-token"}
            )
        assert res.status_code == 200
        assert res.json()["status"] == "success"


# ------------------------------------------------------------------
# Test 2: GPU fields set to null -> accepted
# ------------------------------------------------------------------
def test_schema_null_gpu_fields_report():
    """Pydantic model must validate a report where GPU fields are all null."""
    payload = AgentReportPayload(**VALID_NULL_GPU_REPORT)
    gpu = payload.system_metrics.gpu
    assert gpu is not None
    assert gpu.model is None
    assert gpu.vendor is None
    assert gpu.core_count is None
    assert gpu.metal_supported is None
    assert gpu.metal_family is None
    assert gpu.utilization is None


def test_schema_none_gpu_object_report():
    """Pydantic model must validate a report where gpu key is null/None."""
    payload = AgentReportPayload(**VALID_NONE_GPU_OBJECT_REPORT)
    assert payload.system_metrics.gpu is None


@pytest.mark.asyncio
async def test_endpoint_null_gpu_fields_accepted(transport):
    """POST /api/v1/agents/report accepts GCP/Linux reports with null GPU fields."""
    with patch("app.api.v1.agents.metric_service.process_agent_report", new_callable=AsyncMock) as mock_process:
        mock_process.return_value = {"status": "success", "message": "Metrics processed successfully"}
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.post(
                AGENT_REPORT_URL,
                json=VALID_NULL_GPU_REPORT,
                headers={"Authorization": "Bearer test-token"}
            )
        assert res.status_code == 200
        assert res.json()["status"] == "success"


# ------------------------------------------------------------------
# Test 3: Missing unrelated required report fields -> rejected
# ------------------------------------------------------------------
@pytest.mark.parametrize("missing_key", [
    "machine_information",
    "project",
    "environment",
    "timestamp",
    "agent_version",
    "system_metrics"
])
@pytest.mark.asyncio
async def test_endpoint_missing_required_fields_rejected(transport, missing_key):
    """POST /api/v1/agents/report rejects reports missing required top-level fields (HTTP 422)."""
    invalid_data = dict(VALID_COMPLETE_REPORT)
    invalid_data.pop(missing_key)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            AGENT_REPORT_URL,
            json=invalid_data,
            headers={"Authorization": "Bearer test-token"}
        )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_endpoint_missing_sub_metrics_rejected(transport):
    """POST /api/v1/agents/report rejects report missing required cpu metrics (HTTP 422)."""
    invalid_data = {
        "machine_information": {"name": "test"},
        "project": "p", "environment": "e", "timestamp": "t", "agent_version": "1.0",
        "system_metrics": {
            # Missing cpu
            "memory": {"memory_bytes": 100, "memory_mb": 0.1, "memory_gb": 0.001},
            "storage": {
                "project_bytes": 0, "project_mb": 0, "project_gb": 0,
                "backend_bytes": 0, "backend_mb": 0, "backend_gb": 0,
                "frontend_bytes": 0, "frontend_mb": 0, "frontend_gb": 0,
                "uploads_bytes": 0, "uploads_mb": 0, "uploads_gb": 0
            }
        }
    }
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            AGENT_REPORT_URL,
            json=invalid_data,
            headers={"Authorization": "Bearer test-token"}
        )
    assert res.status_code == 422


# ------------------------------------------------------------------
# Test 4: Invalid unrelated field types -> rejected
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_endpoint_invalid_field_types_rejected(transport):
    """POST /api/v1/agents/report rejects invalid types in cpu_percent or core_count (HTTP 422)."""
    invalid_data = dict(VALID_COMPLETE_REPORT)
    # Give non-float string to cpu_percent
    invalid_data["system_metrics"] = dict(VALID_COMPLETE_REPORT["system_metrics"])
    invalid_data["system_metrics"]["cpu"] = {"cpu_percent": "invalid_not_a_number"}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            AGENT_REPORT_URL,
            json=invalid_data,
            headers={"Authorization": "Bearer test-token"}
        )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_endpoint_invalid_gpu_core_count_type_rejected(transport):
    """POST /api/v1/agents/report rejects non-integer string in gpu.core_count (HTTP 422)."""
    invalid_data = dict(VALID_COMPLETE_REPORT)
    invalid_data["system_metrics"] = dict(VALID_COMPLETE_REPORT["system_metrics"])
    invalid_data["system_metrics"]["gpu"] = {
        "model": "Apple M2",
        "vendor": "Apple",
        "core_count": "invalid_int_string",
        "metal_supported": True,
        "metal_family": "metal3",
        "utilization": 10.0
    }

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            AGENT_REPORT_URL,
            json=invalid_data,
            headers={"Authorization": "Bearer test-token"}
        )
    assert res.status_code == 422


# ------------------------------------------------------------------
# Test 5: Existing auth/authz behavior remains unchanged
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_endpoint_missing_auth_header_rejected(transport):
    """POST /api/v1/agents/report without Authorization header returns 403 Forbidden."""
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(AGENT_REPORT_URL, json=VALID_COMPLETE_REPORT)
    # HTTPBearer returns 401 or 403 when header is missing
    assert res.status_code in (401, 403)
