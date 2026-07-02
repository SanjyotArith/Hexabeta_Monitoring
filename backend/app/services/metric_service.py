import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException

from app.schemas.agent_report import AgentReportPayload
from app.repositories import metric_repository
from app.models.infrastructure import Agent, Project, Environment, Machine

logger = logging.getLogger("hexamonitor.agent")

async def get_or_create_machine(db: AsyncSession, payload: AgentReportPayload) -> Machine:
    # 1. Get or create Project
    result = await db.execute(select(Project).where(Project.name == payload.project))
    project = result.scalars().first()
    if not project:
        project = Project(name=payload.project)
        db.add(project)
        await db.commit()
        await db.refresh(project)
        
    # 2. Get or create Environment
    result = await db.execute(select(Environment).where(
        (Environment.name == payload.environment) & 
        (Environment.project_id == project.id)
    ))
    environment = result.scalars().first()
    if not environment:
        environment = Environment(name=payload.environment, project_id=project.id)
        db.add(environment)
        await db.commit()
        await db.refresh(environment)
        
    # 3. Get or create Machine
    result = await db.execute(select(Machine).where(
        (Machine.name == payload.machine_information.name) & 
        (Machine.environment_id == environment.id)
    ))
    machine = result.scalars().first()
    if not machine:
        machine = Machine(name=payload.machine_information.name, environment_id=environment.id)
        db.add(machine)
        await db.commit()
        await db.refresh(machine)
        
    return machine

async def process_agent_report(db: AsyncSession, payload: AgentReportPayload):
    logger.info(f"Agent Report Received")
    
    try:
        # Get or create infrastructure
        machine = await get_or_create_machine(db, payload)
        
        # Store metrics
        await metric_repository.insert_metrics(db, machine.id, payload)
        logger.info("Metrics Stored", extra={"machine_id": machine.id})
        
        # Update Machine Status
        await metric_repository.update_machine_status(db, machine.id)
        logger.info("Agent Connected", extra={"machine_id": machine.id})
        
        return {"status": "success", "message": "Metrics processed successfully"}
        
    except Exception as e:
        logger.error(f"Database Error processing agent report: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal database error processing metrics")
