from datetime import datetime
from typing import List
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.database import get_db
from app.models.infrastructure import Agent, Service
from app.models.telemetry import Heartbeat, MachineMetric, ServiceStatusHistory, Log
from app.models.scheduler import SchedulerJob, SchedulerRun
from app.schemas.agent_ingest import HeartbeatIngest, MetricIngest, ServiceStatusIngest, SchedulerJobRunIngest, LogLineIngest
from app.api.deps import get_current_agent

router = APIRouter()

@router.post("/heartbeat", status_code=status.HTTP_204_NO_CONTENT)
async def ingest_heartbeat(
    payload: HeartbeatIngest,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent)
):
    """Ingests agent heartbeat pings to verify host connection latency and status."""
    now = datetime.utcnow()
    agent.last_connected_at = now
    agent.status = "active"
    
    heartbeat_entry = Heartbeat(
        agent_id=agent.id,
        timestamp=now,
        latency_ms=payload.latency_ms
    )
    db.add(heartbeat_entry)
    await db.commit()
    return


@router.post("/metrics", status_code=status.HTTP_204_NO_CONTENT)
async def ingest_metrics(
    payload: MetricIngest,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent)
):
    """Stores system hardware performance data (CPU, RAM, Disk, Temperature)."""
    metric_entry = MachineMetric(
        machine_id=agent.machine_id,
        timestamp=payload.timestamp,
        cpu_usage=payload.cpu_usage,
        ram_used_bytes=payload.ram_used_bytes,
        ram_total_bytes=payload.ram_total_bytes,
        disk_used_bytes=payload.disk_used_bytes,
        disk_total_bytes=payload.disk_total_bytes,
        network_in_bytes_sec=payload.network_in_bytes_sec,
        network_out_bytes_sec=payload.network_out_bytes_sec,
        temperature_celsius=payload.temperature_celsius,
        swap_used_bytes=payload.swap_used_bytes,
        swap_total_bytes=payload.swap_total_bytes,
        load_avg_1m=payload.load_avg_1m,
        load_avg_5m=payload.load_avg_5m,
        load_avg_15m=payload.load_avg_15m,
        uptime_seconds=payload.uptime_seconds
    )
    db.add(metric_entry)
    
    # Update agent connection timestamp
    agent.last_connected_at = datetime.utcnow()
    agent.status = "active"
    await db.commit()
    
    # Trigger alert evaluation for machine metrics
    from app.services.alert_engine import evaluate_machine_metrics_alerts
    await evaluate_machine_metrics_alerts(db, agent.machine_id, metric_entry)
    return


@router.post("/services", status_code=status.HTTP_204_NO_CONTENT)
async def ingest_services(
    payloads: List[ServiceStatusIngest],
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent)
):
    """Processes service status changes, auto-registering untracked services."""
    from app.services.alert_engine import evaluate_service_status_alerts
    
    for status_in in payloads:
        # Find or create Service record
        result = await db.execute(
            select(Service)
            .where((Service.machine_id == agent.machine_id) & (Service.name == status_in.service_name))
        )
        service = result.scalars().first()
        
        if not service:
            # Auto-register newly discovered process
            service = Service(
                machine_id=agent.machine_id,
                name=status_in.service_name,
                service_type="launchd",
                is_active=True
            )
            db.add(service)
            await db.commit()
            await db.refresh(service)
            
        history_entry = ServiceStatusHistory(
            service_id=service.id,
            timestamp=status_in.timestamp,
            status=status_in.status,
            cpu_usage=status_in.cpu_usage,
            ram_used_bytes=status_in.ram_used_bytes,
            details=status_in.details
        )
        db.add(history_entry)
        await db.commit()
        
        # Trigger alert evaluation for service status changes
        await evaluate_service_status_alerts(db, service, status_in.status)
        
    return


@router.post("/scheduler", status_code=status.HTTP_204_NO_CONTENT)
async def ingest_scheduler(
    payloads: List[SchedulerJobRunIngest],
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent)
):
    """Records execution status and logs of background cron jobs run on monitored hosts."""
    for run_in in payloads:
        # Find or create SchedulerJob
        result = await db.execute(
            select(SchedulerJob)
            .where((SchedulerJob.machine_id == agent.machine_id) & (SchedulerJob.name == run_in.job_name))
        )
        job = result.scalars().first()
        
        if not job:
            job = SchedulerJob(
                machine_id=agent.machine_id,
                name=run_in.job_name,
                schedule_cron=run_in.schedule_cron
            )
            db.add(job)
            await db.commit()
            await db.refresh(job)
            
        # Update job record timestamps
        job.last_run_at = run_in.started_at
        job.last_run_status = run_in.status
        
        # Add execution details record
        run_entry = SchedulerRun(
            job_id=job.id,
            started_at=run_in.started_at,
            finished_at=run_in.finished_at,
            status=run_in.status,
            duration_ms=run_in.duration_ms,
            output_log=run_in.output_log
        )
        db.add(run_entry)
        await db.commit()
    return


@router.post("/logs", status_code=status.HTTP_204_NO_CONTENT)
async def ingest_logs(
    payloads: List[LogLineIngest],
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent)
):
    """Appends syslog, Nginx logs, and application events to the log repository."""
    for log_in in payloads:
        # Map logs to service if name matches (e.g. log_type contains nginx -> Nginx service)
        service_id = None
        if log_in.log_type:
            svc_res = await db.execute(
                select(Service)
                .where((Service.machine_id == agent.machine_id) & (Service.name.ilike(f"%{log_in.log_type}%")))
            )
            service = svc_res.scalars().first()
            if service:
                service_id = service.id
                
        log_entry = Log(
            machine_id=agent.machine_id,
            service_id=service_id,
            timestamp=log_in.timestamp,
            log_type=log_in.log_type,
            severity=log_in.severity,
            message=log_in.message,
            metadata_json=log_in.metadata
        )
        db.add(log_entry)
        
    await db.commit()
    return
