from pydantic import BaseModel
from typing import Optional

class CPUReport(BaseModel):
    cpu_percent: float

class MemoryReport(BaseModel):
    memory_bytes: int
    memory_mb: float
    memory_gb: float

class StorageReport(BaseModel):
    project_bytes: int
    project_mb: float
    project_gb: float
    backend_bytes: int
    backend_mb: float
    backend_gb: float
    frontend_bytes: int
    frontend_mb: float
    frontend_gb: float
    uploads_bytes: int
    uploads_mb: float
    uploads_gb: float

class GPUReport(BaseModel):
    model: str
    vendor: str
    core_count: int
    metal_supported: bool
    metal_family: str
    utilization: float

class SystemMetrics(BaseModel):
    cpu: CPUReport
    memory: MemoryReport
    storage: StorageReport
    gpu: GPUReport

class MachineInformation(BaseModel):
    name: str

class AgentReportPayload(BaseModel):
    machine_information: MachineInformation
    project: str
    environment: str
    timestamp: str
    system_metrics: SystemMetrics
    agent_version: str
