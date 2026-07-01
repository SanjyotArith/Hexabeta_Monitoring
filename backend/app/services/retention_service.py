from datetime import datetime, timedelta
from sqlalchemy import delete
from sqlalchemy.future import select

from app.core.database import SessionLocal
from app.models.telemetry import Settings, MachineMetric, ApiCheckHistory, Heartbeat, Log, ServiceStatusHistory
from app.models.scheduler import SchedulerRun

async def run_data_retention_cleanup():
    """Deletes telemetry metrics, check logs, and heartbeats older than retention configurations."""
    async with SessionLocal() as db:
        # Default retention to 30 days if not set in DB
        retention_days = 30
        res = await db.execute(select(Settings).where(Settings.key == "data_retention_days"))
        setting = res.scalars().first()
        if setting:
            try:
                retention_days = int(setting.value)
            except ValueError:
                pass
                
        cutoff = datetime.utcnow() - timedelta(days=retention_days)
        print(f"[RETENTION] Cutoff date: {cutoff} ({retention_days} days). Starting purge...")
        
        try:
            # Delete old database entries
            m_res = await db.execute(delete(MachineMetric).where(MachineMetric.timestamp < cutoff))
            a_res = await db.execute(delete(ApiCheckHistory).where(ApiCheckHistory.timestamp < cutoff))
            h_res = await db.execute(delete(Heartbeat).where(Heartbeat.timestamp < cutoff))
            l_res = await db.execute(delete(Log).where(Log.timestamp < cutoff))
            s_res = await db.execute(delete(SchedulerRun).where(SchedulerRun.started_at < cutoff))
            v_res = await db.execute(delete(ServiceStatusHistory).where(ServiceStatusHistory.timestamp < cutoff))
            
            await db.commit()
            print("[RETENTION] Cleanup finalized successfully.")
        except Exception as e:
            await db.rollback()
            print(f"[RETENTION] Error running cleanup transaction: {e}")
