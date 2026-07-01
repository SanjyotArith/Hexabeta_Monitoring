from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import desc

from app.core.database import get_db
from app.models.infrastructure import Project, Environment, Machine, Service
from app.models.alerting import Incident
from app.models.telemetry import MachineMetric, ApiCheck
from app.models.users import User
from app.api.deps import get_current_user
from pydantic import BaseModel

router = APIRouter()

# Pydantic Schemas for Responses
class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None

class ProjectResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    class Config:
        from_attributes = True

class EnvironmentCreate(BaseModel):
    name: str

class EnvironmentResponse(BaseModel):
    id: int
    project_id: int
    name: str
    created_at: datetime
    updated_at: datetime
    class Config:
        from_attributes = True

class MachineResponse(BaseModel):
    id: int
    environment_id: int
    name: str
    hostname: Optional[str] = None
    ip_address: Optional[str] = None
    os: str
    cpu_cores: Optional[int] = None
    ram_total_bytes: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    class Config:
        from_attributes = True

class ServiceResponse(BaseModel):
    id: int
    machine_id: int
    name: str
    service_type: str
    process_identifier: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    class Config:
        from_attributes = True

class IncidentResponse(BaseModel):
    id: int
    environment_id: int
    title: str
    status: str
    severity: str
    started_at: datetime
    acknowledged_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    class Config:
        from_attributes = True

class MachineMetricResponse(BaseModel):
    id: int
    machine_id: int
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
    class Config:
        from_attributes = True

class ProjectSetupRequest(BaseModel):
    project_name: str
    environment_name: str = "Production"
    check_name: Optional[str] = None
    check_url: str

class ProjectSetupResponse(BaseModel):
    project: ProjectResponse
    environment: EnvironmentResponse


# --- Endpoints ---

# 1. Projects
@router.get("/projects", response_model=List[ProjectResponse])
async def list_projects(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lists all projects."""
    result = await db.execute(select(Project).order_by(Project.name))
    return result.scalars().all()

@router.post("/projects", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    project_in: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Creates a new project."""
    # Check duplicate
    result = await db.execute(select(Project).where(Project.name == project_in.name))
    if result.scalars().first():
        raise HTTPException(status_code=400, detail="Project with this name already exists")
    project = Project(**project_in.model_dump())
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project

# 2. Environments
@router.get("/projects/{project_id}/environments", response_model=List[EnvironmentResponse])
async def list_environments(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lists environments for a specific project."""
    result = await db.execute(
        select(Environment)
        .where(Environment.project_id == project_id)
        .order_by(Environment.name)
    )
    return result.scalars().all()

@router.post("/projects/{project_id}/environments", response_model=EnvironmentResponse, status_code=status.HTTP_201_CREATED)
async def create_environment(
    project_id: int,
    env_in: EnvironmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Creates a new environment under a project."""
    p_result = await db.execute(select(Project).where(Project.id == project_id))
    if not p_result.scalars().first():
        raise HTTPException(status_code=404, detail="Project not found")
        
    result = await db.execute(
        select(Environment)
        .where((Environment.project_id == project_id) & (Environment.name == env_in.name))
    )
    if result.scalars().first():
        raise HTTPException(status_code=400, detail="Environment with this name already exists in this project")
        
    env = Environment(project_id=project_id, **env_in.model_dump())
    db.add(env)
    await db.commit()
    await db.refresh(env)
    return env

# 3. Machines
@router.get("/machines/environments/{env_id}/machines", response_model=List[MachineResponse])
async def list_machines(
    env_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lists all registered machines within an environment."""
    result = await db.execute(select(Machine).where(Machine.environment_id == env_id))
    return result.scalars().all()

# 4. Metrics
@router.get("/metrics/machines/{machine_id}/current", response_model=Optional[MachineMetricResponse])
async def get_current_metrics(
    machine_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Gets the latest hardware utilization metric entry for a machine."""
    result = await db.execute(
        select(MachineMetric)
        .where(MachineMetric.machine_id == machine_id)
        .order_by(desc(MachineMetric.timestamp))
        .limit(1)
    )
    return result.scalars().first()

# 5. Services
@router.get("/services/machines/{machine_id}", response_model=List[ServiceResponse])
async def list_services(
    machine_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lists all services running on a specific machine."""
    result = await db.execute(select(Service).where(Service.machine_id == machine_id))
    return result.scalars().all()

# 6. Incidents
@router.get("/incidents/environments/{env_id}/active", response_model=List[IncidentResponse])
async def list_active_incidents(
    env_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retrieves unresolved incidents within an environment."""
    result = await db.execute(
        select(Incident)
        .where((Incident.environment_id == env_id) & (Incident.status != "resolved"))
    )
    return result.scalars().all()

@router.post("/incidents/{incident_id}/acknowledge", response_model=IncidentResponse)
async def acknowledge_incident(
    incident_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Acknowledges an active incident."""
    result = await db.execute(select(Incident).where(Incident.id == incident_id))
    incident = result.scalars().first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
        
    incident.status = "acknowledged"
    incident.acknowledged_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(incident)
    return incident


@router.post("/projects/setup", response_model=ProjectSetupResponse)
async def setup_project_with_monitor(
    setup_in: ProjectSetupRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Unified setup endpoint: creates Project, Environment, Uptime Check,
    and populates default mock Machine/Services/Metrics.
    """
    # 1. Project
    p_result = await db.execute(select(Project).where(Project.name == setup_in.project_name))
    project = p_result.scalars().first()
    if not project:
        project = Project(
            name=setup_in.project_name,
            description=f"Infrastructure monitoring for {setup_in.project_name}"
        )
        db.add(project)
        await db.flush() # flush to get project.id
        
    # 2. Environment
    e_result = await db.execute(
        select(Environment)
        .where((Environment.project_id == project.id) & (Environment.name == setup_in.environment_name))
    )
    env = e_result.scalars().first()
    if not env:
        env = Environment(
            project_id=project.id,
            name=setup_in.environment_name
        )
        db.add(env)
        await db.flush() # flush to get env.id
        
    # 3. API Check
    check_url = setup_in.check_url
    if not check_url.startswith("http://") and not check_url.startswith("https://"):
        check_url = "https://" + check_url
        
    check_name = setup_in.check_name or f"{setup_in.project_name} Homepage"
    
    # Avoid duplicate check for same URL in same env
    c_result = await db.execute(
        select(ApiCheck)
        .where((ApiCheck.environment_id == env.id) & (ApiCheck.url == check_url))
    )
    check = c_result.scalars().first()
    if not check:
        check = ApiCheck(
            environment_id=env.id,
            name=check_name,
            url=check_url,
            request_method="GET",
            is_active=True
        )
        db.add(check)
        await db.flush()
        
    # 4. Mock Machine & Metrics (only if no machine exists in this env)
    m_result = await db.execute(select(Machine).where(Machine.environment_id == env.id))
    machine = m_result.scalars().first()
    if not machine:
        machine = Machine(
            environment_id=env.id,
            name="Mac Mini #1",
            hostname="mac-mini-1.local",
            ip_address="192.168.1.10",
            os="macOS",
            cpu_cores=8,
            ram_total_bytes=17179869184
        )
        db.add(machine)
        await db.flush()
        
        # Default services
        services_list = [
            ("Backend API", "launchd"),
            ("Nginx", "process"),
            ("PostgreSQL", "process"),
            ("Cloudflare Tunnel", "process")
        ]
        for name, service_type in services_list:
            svc = Service(
                machine_id=machine.id,
                name=name,
                service_type=service_type,
                is_active=True
            )
            db.add(svc)
            
        # Default metrics
        metric = MachineMetric(
            machine_id=machine.id,
            timestamp=datetime.now(timezone.utc),
            cpu_usage=12.5,
            ram_used_bytes=6442450944,
            ram_total_bytes=17179869184,
            disk_used_bytes=125000000000,
            disk_total_bytes=500000000000,
            network_in_bytes_sec=45000,
            network_out_bytes_sec=25000,
            load_avg_1m=1.1,
            uptime_seconds=86400
        )
        db.add(metric)
        
    await db.commit()
    
    # Refresh to load relations
    await db.refresh(project)
    await db.refresh(env)
    
    return {
        "project": project,
        "environment": env
    }
