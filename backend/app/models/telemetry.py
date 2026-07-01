from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text, BigInteger, Double, JSON
from sqlalchemy.orm import relationship
from app.core.database import Base

class Heartbeat(Base):
    __tablename__ = "heartbeats"
    
    id = Column(BigInteger, primary_key=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, index=True)
    latency_ms = Column(Integer, nullable=True)
    
    agent = relationship("Agent", back_populates="heartbeats")


class MachineMetric(Base):
    __tablename__ = "machine_metrics"
    
    id = Column(BigInteger, primary_key=True, index=True)
    machine_id = Column(Integer, ForeignKey("machines.id", ondelete="CASCADE"), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    cpu_usage = Column(Double, nullable=False)
    ram_used_bytes = Column(BigInteger, nullable=False)
    ram_total_bytes = Column(BigInteger, nullable=False)
    disk_used_bytes = Column(BigInteger, nullable=False)
    disk_total_bytes = Column(BigInteger, nullable=False)
    network_in_bytes_sec = Column(Double, nullable=False)
    network_out_bytes_sec = Column(Double, nullable=False)
    temperature_celsius = Column(Double, nullable=True)
    swap_used_bytes = Column(BigInteger, nullable=True)
    swap_total_bytes = Column(BigInteger, nullable=True)
    load_avg_1m = Column(Double, nullable=True)
    load_avg_5m = Column(Double, nullable=True)
    load_avg_15m = Column(Double, nullable=True)
    uptime_seconds = Column(BigInteger, nullable=True)
    
    machine = relationship("Machine", back_populates="metrics")


class ServiceStatusHistory(Base):
    __tablename__ = "service_status_history"
    
    id = Column(BigInteger, primary_key=True, index=True)
    service_id = Column(Integer, ForeignKey("services.id", ondelete="CASCADE"), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    status = Column(String(20), nullable=False) # 'running', 'stopped', 'failed', 'unknown'
    cpu_usage = Column(Double, nullable=True)
    ram_used_bytes = Column(BigInteger, nullable=True)
    details = Column(Text, nullable=True)
    
    service = relationship("Service", back_populates="status_history")


class ApiCheck(Base):
    __tablename__ = "api_checks"
    
    id = Column(Integer, primary_key=True, index=True)
    environment_id = Column(Integer, ForeignKey("environments.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    url = Column(Text, nullable=False)
    request_method = Column(String(10), nullable=False, default="GET")
    headers = Column(JSON, nullable=True)
    request_payload = Column(Text, nullable=True)
    expected_status_code = Column(Integer, nullable=False, default=200)
    expected_response_match = Column(Text, nullable=True)
    check_interval_seconds = Column(Integer, nullable=False, default=60)
    timeout_seconds = Column(Integer, nullable=False, default=10)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    environment = relationship("Environment", back_populates="api_checks")
    history = relationship("ApiCheckHistory", back_populates="api_check", cascade="all, delete-orphan")


class ApiCheckHistory(Base):
    __tablename__ = "api_check_history"
    
    id = Column(BigInteger, primary_key=True, index=True)
    api_check_id = Column(Integer, ForeignKey("api_checks.id", ondelete="CASCADE"), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    is_up = Column(Boolean, nullable=False)
    response_time_ms = Column(Integer, nullable=True)
    status_code = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    
    api_check = relationship("ApiCheck", back_populates="history")


class Log(Base):
    __tablename__ = "logs"
    
    id = Column(BigInteger, primary_key=True, index=True)
    machine_id = Column(Integer, ForeignKey("machines.id", ondelete="CASCADE"), nullable=False, index=True)
    service_id = Column(Integer, ForeignKey("services.id", ondelete="SET NULL"), nullable=True, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    log_type = Column(String(50), nullable=False) # 'nginx_access', 'nginx_error', 'app_error', etc.
    severity = Column(String(20), nullable=False, index=True) # 'debug', 'info', 'warning', 'error', 'critical'
    message = Column(Text, nullable=False)
    metadata_json = Column("metadata", JSON, nullable=True)
    
    machine = relationship("Machine", back_populates="logs")
    service = relationship("Service", back_populates="logs")


class Settings(Base):
    __tablename__ = "settings"
    
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), nullable=False, unique=True, index=True)
    value = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
