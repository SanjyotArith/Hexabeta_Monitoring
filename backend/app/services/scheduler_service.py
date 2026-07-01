import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.future import select
from app.core.database import SessionLocal
from app.models.telemetry import ApiCheck
from app.services.api_check_runner import run_single_api_check
from app.services.retention_service import run_data_retention_cleanup

scheduler = AsyncIOScheduler()

async def execute_synthetic_checks():
    """Queries all active API checks from the database and runs them concurrently."""
    async with SessionLocal() as db:
        result = await db.execute(select(ApiCheck).where(ApiCheck.is_active == True))
        active_checks = result.scalars().all()
        
        if not active_checks:
            return
            
        # Execute checks concurrently using asyncio.gather to avoid blocking
        tasks = [run_single_api_check(db, check) for check in active_checks]
        await asyncio.gather(*tasks, return_exceptions=True)


def start_scheduler():
    """Starts the AsyncIOScheduler and schedules the periodic check task."""
    if not scheduler.running:
        # Runs synthetic URL tests every 10 seconds
        scheduler.add_job(
            execute_synthetic_checks, 
            "interval", 
            seconds=10, 
            id="api_synthetic_checks",
            max_instances=1
        )
        # Runs database retention cleanup once a day at 2:00 AM
        scheduler.add_job(
            run_data_retention_cleanup,
            "cron",
            hour=2,
            minute=0,
            id="database_retention_cleanup"
        )
        scheduler.start()
        print("HexaMonitor background scheduler started.")


def shutdown_scheduler():
    """Gracefully shuts down the background scheduler."""
    if scheduler.running:
        scheduler.shutdown()
        print("HexaMonitor background scheduler stopped.")
