from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import desc
from datetime import datetime

from app.models.phase1 import AgentMetricReport, StorageMetric, GPUMetric
from app.models.infrastructure import Machine, Agent
from app.schemas.agent_report import AgentReportPayload
import dateutil.parser

async def insert_metrics(db: AsyncSession, machine_id: int, payload: AgentReportPayload):
    try:
        timestamp_dt = dateutil.parser.isoparse(payload.timestamp)
    except Exception:
        timestamp_dt = datetime.utcnow()
        
    report = AgentMetricReport(
        machine_id=machine_id,
        timestamp=timestamp_dt,
        cpu_percent=payload.system_metrics.cpu.cpu_percent,
        memory_bytes=payload.system_metrics.memory.memory_bytes,
        memory_mb=payload.system_metrics.memory.memory_mb,
        memory_gb=payload.system_metrics.memory.memory_gb,
    )
    db.add(report)
    await db.flush() # flush to get report.id
    
    storage_metric = StorageMetric(
        report_id=report.id,
        project_bytes=payload.system_metrics.storage.project_bytes,
        project_mb=payload.system_metrics.storage.project_mb,
        project_gb=payload.system_metrics.storage.project_gb,
        backend_bytes=payload.system_metrics.storage.backend_bytes,
        backend_mb=payload.system_metrics.storage.backend_mb,
        backend_gb=payload.system_metrics.storage.backend_gb,
        frontend_bytes=payload.system_metrics.storage.frontend_bytes,
        frontend_mb=payload.system_metrics.storage.frontend_mb,
        frontend_gb=payload.system_metrics.storage.frontend_gb,
        uploads_bytes=payload.system_metrics.storage.uploads_bytes,
        uploads_mb=payload.system_metrics.storage.uploads_mb,
        uploads_gb=payload.system_metrics.storage.uploads_gb,
    )
    db.add(storage_metric)
    
    gpu_metric = GPUMetric(
        report_id=report.id,
        model=payload.system_metrics.gpu.model,
        vendor=payload.system_metrics.gpu.vendor,
        core_count=payload.system_metrics.gpu.core_count,
        metal_supported=payload.system_metrics.gpu.metal_supported,
        metal_family=payload.system_metrics.gpu.metal_family,
        utilization=payload.system_metrics.gpu.utilization
    )
    db.add(gpu_metric)
    
    await db.commit()
    await db.refresh(report)
    return report


async def update_machine_status(db: AsyncSession, machine_id: int):
    # Fetch the agent associated with this machine to update its last connected time
    result = await db.execute(select(Agent).where(Agent.machine_id == machine_id))
    agent = result.scalars().first()
    
    if agent:
        agent.last_connected_at = datetime.utcnow()
        agent.status = "active"
        
    # Update machine's updated_at
    result_machine = await db.execute(select(Machine).where(Machine.id == machine_id))
    machine = result_machine.scalars().first()
    if machine:
        machine.updated_at = datetime.utcnow()
        
    await db.commit()


async def get_latest_metrics(db: AsyncSession):
    result = await db.execute(
        select(AgentMetricReport)
        .order_by(desc(AgentMetricReport.timestamp))
        .limit(1)
    )
    report = result.scalars().first()
    
    if report:
        # Load related metrics
        await db.refresh(report, ["storage", "gpu"])
    return report


async def get_historical_metrics(db: AsyncSession, limit: int = 100):
    result = await db.execute(
        select(AgentMetricReport)
        .order_by(desc(AgentMetricReport.timestamp))
        .limit(limit)
    )
    reports = result.scalars().all()
    
    for report in reports:
        await db.refresh(report, ["storage", "gpu"])
    
    # Return chronologically ordered
    return list(reversed(reports))
