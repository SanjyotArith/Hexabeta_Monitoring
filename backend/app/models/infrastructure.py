from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text, BigInteger, UniqueConstraint
from sqlalchemy.orm import relationship
from app.core.database import Base

class Project(Base):
    __tablename__ = "projects"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    environments = relationship("Environment", back_populates="project", cascade="all, delete-orphan")


class Environment(Base):
    __tablename__ = "environments"
    
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(50), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    project = relationship("Project", back_populates="environments")
    machines = relationship("Machine", back_populates="environment", cascade="all, delete-orphan")
    api_checks = relationship("ApiCheck", back_populates="environment", cascade="all, delete-orphan")
    alert_rules = relationship("AlertRule", back_populates="environment", cascade="all, delete-orphan")
    incidents = relationship("Incident", back_populates="environment", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("project_id", "name", name="unique_project_env"),
    )


class Machine(Base):
    __tablename__ = "machines"
    
    id = Column(Integer, primary_key=True, index=True)
    environment_id = Column(Integer, ForeignKey("environments.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    hostname = Column(String(255), nullable=True)
    ip_address = Column(String(45), nullable=True)
    os = Column(String(100), nullable=False, default="macOS")
    cpu_cores = Column(Integer, nullable=True)
    ram_total_bytes = Column(BigInteger, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    environment = relationship("Environment", back_populates="machines")
    agent = relationship("Agent", back_populates="machine", uselist=False, cascade="all, delete-orphan")
    services = relationship("Service", back_populates="machine", cascade="all, delete-orphan")
    metrics = relationship("MachineMetric", back_populates="machine", cascade="all, delete-orphan")
    logs = relationship("Log", back_populates="machine", cascade="all, delete-orphan")
    scheduler_jobs = relationship("SchedulerJob", back_populates="machine", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="machine")

    __table_args__ = (
        UniqueConstraint("environment_id", "name", name="unique_env_machine"),
    )


class Agent(Base):
    __tablename__ = "agents"
    
    id = Column(Integer, primary_key=True, index=True)
    machine_id = Column(Integer, ForeignKey("machines.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    token_hash = Column(String(255), nullable=False, unique=True, index=True)
    version = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False, default="inactive")
    last_connected_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    machine = relationship("Machine", back_populates="agent")
    heartbeats = relationship("Heartbeat", back_populates="agent", cascade="all, delete-orphan")


class Service(Base):
    __tablename__ = "services"
    
    id = Column(Integer, primary_key=True, index=True)
    machine_id = Column(Integer, ForeignKey("machines.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    service_type = Column(String(50), nullable=False) # 'launchd', 'process', 'port'
    process_identifier = Column(String(255), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    machine = relationship("Machine", back_populates="services")
    status_history = relationship("ServiceStatusHistory", back_populates="service", cascade="all, delete-orphan")
    logs = relationship("Log", back_populates="service")
    alerts = relationship("Alert", back_populates="service")

    __table_args__ = (
        UniqueConstraint("machine_id", "name", name="unique_machine_service"),
    )
