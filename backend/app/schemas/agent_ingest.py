from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel

class HeartbeatIngest(BaseModel):
    latency_ms: Optional[int] = None

class MetricIngest(BaseModel):
    timestamp: datetime
    cpu_usage: float
    ram_used_bytes: int
    ram_total_bytes: int
    disk_used_bytes: int
    disk_total_bytes: int
    network_in_bytes_sec: float
    network_out_bytes_sec: float
    temperature_celsius: Optional[float] = None
    swap_used_bytes: Optional[int] = None
    swap_total_bytes: Optional[int] = None
    load_avg_1m: Optional[float] = None
    load_avg_5m: Optional[float] = None
    load_avg_15m: Optional[float] = None
    uptime_seconds: Optional[int] = None

class ServiceStatusIngest(BaseModel):
    service_name: str
    timestamp: datetime
    status: str  # 'running', 'stopped', 'failed', 'unknown'
    cpu_usage: Optional[float] = None
    ram_used_bytes: Optional[int] = None
    details: Optional[str] = None

class SchedulerJobRunIngest(BaseModel):
    job_name: str
    schedule_cron: Optional[str] = None
    started_at: datetime
    finished_at: Optional[datetime] = None
    status: str  # 'running', 'success', 'failed'
    duration_ms: Optional[int] = None
    output_log: Optional[str] = None

class LogLineIngest(BaseModel):
    timestamp: datetime
    log_type: str  # 'nginx_access', 'nginx_error', 'app_error', etc.
    severity: str  # 'debug', 'info', 'warning', 'error', 'critical'
    message: str
    metadata: Optional[Dict[str, Any]] = None
