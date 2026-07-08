from datetime import datetime, timedelta
from sqlalchemy import delete
from sqlalchemy.future import select

from app.core.database import SessionLocal
from app.models.telemetry import Settings, MachineMetric, ApiCheckHistory, Heartbeat, Log, ServiceStatusHistory
from app.models.scheduler import SchedulerRun

async def run_data_retention_cleanup():
    """Deletes telemetry data older than configured retention, and ALL logs_* rows older than 24h."""
    async with SessionLocal() as db:
        # ── General retention (metrics, heartbeats, etc.) ──────────────────
        retention_days = 30
        res = await db.execute(select(Settings).where(Settings.key == "data_retention_days"))
        setting = res.scalars().first()
        if setting:
            try:
                retention_days = int(setting.value)
            except ValueError:
                pass

        cutoff     = datetime.utcnow() - timedelta(days=retention_days)
        log_cutoff = datetime.utcnow() - timedelta(hours=24)
        print(f"[RETENTION] General cutoff={cutoff}  |  Log cutoff (24h)={log_cutoff}")

        try:
            await db.execute(delete(MachineMetric).where(MachineMetric.timestamp < cutoff))
            await db.execute(delete(ApiCheckHistory).where(ApiCheckHistory.timestamp < cutoff))
            await db.execute(delete(Heartbeat).where(Heartbeat.timestamp < cutoff))
            # Also purge main logs table (legacy) older than 24h
            await db.execute(delete(Log).where(Log.timestamp < log_cutoff))
            await db.execute(delete(SchedulerRun).where(SchedulerRun.started_at < cutoff))
            await db.execute(delete(ServiceStatusHistory).where(ServiceStatusHistory.timestamp < cutoff))
            await db.commit()

            # ── Per-service log tables (logs_nginx, logs_backend, …) ───────
            from sqlalchemy import text
            result = await db.execute(text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = current_schema() "
                "  AND table_name LIKE 'logs\\_%' ESCAPE '\\\\'"
            ))
            log_tables = [row[0] for row in result.fetchall()]

            purged_total = 0
            for tbl in log_tables:
                del_res = await db.execute(
                    text(f"DELETE FROM {tbl} WHERE timestamp < :cutoff"),
                    {"cutoff": log_cutoff}
                )
                purged_total += del_res.rowcount or 0

            await db.commit()
            print(f"[RETENTION] Purged {purged_total} log rows across {len(log_tables)} service tables.")
        except Exception as e:
            await db.rollback()
            print(f"[RETENTION] Error: {e}")
