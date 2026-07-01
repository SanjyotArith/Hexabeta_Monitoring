from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, BigInteger, UniqueConstraint
from sqlalchemy.orm import relationship
from app.core.database import Base

class SchedulerJob(Base):
    __tablename__ = "scheduler_jobs"
    
    id = Column(Integer, primary_key=True, index=True)
    machine_id = Column(Integer, ForeignKey("machines.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    schedule_cron = Column(String(100), nullable=True)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    last_run_status = Column(String(20), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    machine = relationship("Machine", back_populates="scheduler_jobs")
    runs = relationship("SchedulerRun", back_populates="job", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("machine_id", "name", name="unique_machine_job"),
    )


class SchedulerRun(Base):
    __tablename__ = "scheduler_runs"
    
    id = Column(BigInteger, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("scheduler_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    started_at = Column(DateTime(timezone=True), nullable=False, index=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(20), nullable=False) # 'running', 'success', 'failed'
    duration_ms = Column(Integer, nullable=True)
    output_log = Column(Text, nullable=True)
    
    job = relationship("SchedulerJob", back_populates="runs")
