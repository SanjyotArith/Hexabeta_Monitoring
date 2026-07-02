from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text, BigInteger, Double, JSON
from sqlalchemy.orm import relationship
from app.core.database import Base

class AgentMetricReport(Base):
    __tablename__ = "phase1_metric_reports"
    
    id = Column(Integer, primary_key=True, index=True)
    machine_id = Column(Integer, ForeignKey("machines.id", ondelete="CASCADE"), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    
    # CPU
    cpu_percent = Column(Double, nullable=False)
    
    # Memory
    memory_bytes = Column(BigInteger, nullable=False)
    memory_mb = Column(Double, nullable=False)
    memory_gb = Column(Double, nullable=False)
    
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    
    machine = relationship("Machine")
    storage = relationship("StorageMetric", back_populates="report", uselist=False, cascade="all, delete-orphan")
    gpu = relationship("GPUMetric", back_populates="report", uselist=False, cascade="all, delete-orphan")


class StorageMetric(Base):
    __tablename__ = "phase1_storage_metrics"
    
    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(Integer, ForeignKey("phase1_metric_reports.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    
    project_bytes = Column(BigInteger, nullable=False)
    project_mb = Column(Double, nullable=False)
    project_gb = Column(Double, nullable=False)
    
    backend_bytes = Column(BigInteger, nullable=False)
    backend_mb = Column(Double, nullable=False)
    backend_gb = Column(Double, nullable=False)
    
    frontend_bytes = Column(BigInteger, nullable=False)
    frontend_mb = Column(Double, nullable=False)
    frontend_gb = Column(Double, nullable=False)
    
    uploads_bytes = Column(BigInteger, nullable=False)
    uploads_mb = Column(Double, nullable=False)
    uploads_gb = Column(Double, nullable=False)
    
    report = relationship("AgentMetricReport", back_populates="storage")


class GPUMetric(Base):
    __tablename__ = "phase1_gpu_metrics"
    
    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(Integer, ForeignKey("phase1_metric_reports.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    
    model = Column(String(100), nullable=True)
    vendor = Column(String(100), nullable=True)
    core_count = Column(Integer, nullable=True)
    metal_supported = Column(Boolean, nullable=True)
    metal_family = Column(String(100), nullable=True)
    utilization = Column(Double, nullable=True)
    
    report = relationship("AgentMetricReport", back_populates="gpu")
