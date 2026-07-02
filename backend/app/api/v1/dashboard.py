from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.repositories import metric_repository

router = APIRouter()

@router.get("/system")
async def get_dashboard_system_latest(db: AsyncSession = Depends(get_db)):
    """
    Returns latest CPU, RAM, GPU, and Storage for the dashboard.
    """
    report = await metric_repository.get_latest_metrics(db)
    
    if not report:
        return {"status": "no_data"}
        
    return {
        "status": "success",
        "timestamp": report.timestamp,
        "CPU": {
            "utilization": report.cpu_percent
        },
        "RAM": {
            "used_bytes": report.memory_bytes,
            "used_mb": report.memory_mb,
            "used_gb": report.memory_gb,
        },
        "GPU": {
            "model": report.gpu.model if report.gpu else "Unknown",
            "utilization": report.gpu.utilization if report.gpu else 0.0,
            "core_count": report.gpu.core_count if report.gpu else 0
        },
        "Project Storage": {
            "gb": report.storage.project_gb if report.storage else 0.0
        },
        "Backend Storage": {
            "gb": report.storage.backend_gb if report.storage else 0.0
        },
        "Frontend Storage": {
            "gb": report.storage.frontend_gb if report.storage else 0.0
        },
        "Uploads Storage": {
            "gb": report.storage.uploads_gb if report.storage else 0.0
        }
    }


@router.get("/historical/{metric_type}")
async def get_dashboard_historical(metric_type: str, limit: int = 20, db: AsyncSession = Depends(get_db)):
    """
    Returns historical data for CPU, RAM, GPU, or Storage.
    Valid metric_type values: cpu, ram, gpu, storage
    """
    reports = await metric_repository.get_historical_metrics(db, limit)
    
    data = []
    for r in reports:
        entry = {"timestamp": r.timestamp}
        if metric_type == "cpu":
            entry["utilization"] = r.cpu_percent
        elif metric_type == "ram":
            entry["used_gb"] = r.memory_gb
        elif metric_type == "gpu":
            entry["utilization"] = r.gpu.utilization if r.gpu else 0.0
        elif metric_type == "storage":
            entry["project_gb"] = r.storage.project_gb if r.storage else 0.0
            entry["backend_gb"] = r.storage.backend_gb if r.storage else 0.0
            entry["frontend_gb"] = r.storage.frontend_gb if r.storage else 0.0
            entry["uploads_gb"] = r.storage.uploads_gb if r.storage else 0.0
            
        data.append(entry)
        
    return {"status": "success", "data": data}
