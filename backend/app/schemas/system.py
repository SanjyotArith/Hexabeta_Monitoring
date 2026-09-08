"""
HexaAgent — System Schemas.

Pydantic v2 response models for the /api/v1/system endpoint.
All values are raw numerics — formatting belongs to the dashboard.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class CpuMetrics(BaseModel):
    """CPU usage metrics for HexaBeta processes."""

    cpu_percent: float = Field(
        ..., description="Aggregated CPU usage across all HexaBeta processes"
    )


class MemoryMetrics(BaseModel):
    """RSS memory metrics for HexaBeta processes."""

    memory_bytes: int = Field(..., description="Total RSS in bytes")
    memory_mb: float = Field(..., description="Total RSS in megabytes")
    memory_gb: float = Field(..., description="Total RSS in gigabytes")


class StorageMetrics(BaseModel):
    """Disk footprint of the HexaBeta project directories."""

    project_bytes: int = Field(..., description="Total project size in bytes")
    project_mb: float = Field(..., description="Total project size in MB")
    project_gb: float = Field(..., description="Total project size in GB")
    backend_bytes: int = Field(..., description="Backend directory size in bytes")
    backend_mb: float = Field(..., description="Backend directory size in MB")
    backend_gb: float = Field(..., description="Backend directory size in GB")
    frontend_bytes: int = Field(..., description="Frontend directory size in bytes")
    frontend_mb: float = Field(..., description="Frontend directory size in MB")
    frontend_gb: float = Field(..., description="Frontend directory size in GB")
    uploads_bytes: int = Field(..., description="Uploads directory size in bytes")
    uploads_mb: float = Field(..., description="Uploads directory size in MB")
    uploads_gb: float = Field(..., description="Uploads directory size in GB")


class GpuMetrics(BaseModel):
    """GPU information (macOS)."""

    model: Optional[str] = Field(None, description="GPU model name")
    vendor: Optional[str] = Field(None, description="GPU vendor")
    core_count: Optional[int] = Field(None, description="Number of GPU cores")
    metal_supported: Optional[bool] = Field(None, description="Metal API support")
    metal_family: Optional[str] = Field(None, description="Metal family version (e.g. Metal 4)")
    utilization: Optional[float] = Field(
        None,
        description="GPU utilization percent (null on macOS — not reliably available)",
    )


class SystemResponse(BaseModel):
    """
    Aggregated response for GET /api/v1/system.

    Contains all collector outputs in a single JSON payload.
    """

    success: bool = Field(..., description="Whether the collection succeeded")
    timestamp: str = Field(..., description="ISO-8601 collection timestamp")
    cpu: Optional[dict[str, Any]] = Field(None, description="CPU metrics")
    memory: Optional[dict[str, Any]] = Field(None, description="Memory metrics")
    storage: Optional[dict[str, Any]] = Field(None, description="Storage metrics")
    gpu: Optional[dict[str, Any]] = Field(None, description="GPU metrics")
