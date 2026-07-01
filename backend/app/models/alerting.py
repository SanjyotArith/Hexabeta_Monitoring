from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text, Double
from sqlalchemy.orm import relationship
from app.core.database import Base

class AlertRule(Base):
    __tablename__ = "alert_rules"
    
    id = Column(Integer, primary_key=True, index=True)
    environment_id = Column(Integer, ForeignKey("environments.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    check_type = Column(String(50), nullable=False) # 'metric_threshold', 'service_down', 'api_failed', 'agent_offline'
    metric_name = Column(String(50), nullable=True) # e.g. 'cpu_usage'
    operator = Column(String(10), nullable=True) # '>', '<', '=='
    threshold_value = Column(Double, nullable=True)
    duration_seconds = Column(Integer, nullable=False, default=300)
    severity = Column(String(20), nullable=False, default="warning") # 'info', 'warning', 'critical'
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    environment = relationship("Environment", back_populates="alert_rules")
    alerts = relationship("Alert", back_populates="rule", cascade="all, delete-orphan")


class Incident(Base):
    __tablename__ = "incidents"
    
    id = Column(Integer, primary_key=True, index=True)
    environment_id = Column(Integer, ForeignKey("environments.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    status = Column(String(20), nullable=False, default="active", index=True) # 'active', 'acknowledged', 'resolved'
    severity = Column(String(20), nullable=False) # 'warning', 'critical'
    started_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, index=True)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    
    environment = relationship("Environment", back_populates="incidents")
    alerts = relationship("Alert", back_populates="incident")


class Alert(Base):
    __tablename__ = "alerts"
    
    id = Column(Integer, primary_key=True, index=True)
    incident_id = Column(Integer, ForeignKey("incidents.id", ondelete="SET NULL"), nullable=True, index=True)
    alert_rule_id = Column(Integer, ForeignKey("alert_rules.id", ondelete="CASCADE"), nullable=False, index=True)
    machine_id = Column(Integer, ForeignKey("machines.id", ondelete="CASCADE"), nullable=True, index=True)
    service_id = Column(Integer, ForeignKey("services.id", ondelete="CASCADE"), nullable=True, index=True)
    api_check_id = Column(Integer, ForeignKey("api_checks.id", ondelete="CASCADE"), nullable=True, index=True)
    message = Column(Text, nullable=False)
    value_triggered = Column(Double, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    resolved_at = Column(DateTime(timezone=True), nullable=True, index=True) # Index to easily find unresolved alerts
    
    incident = relationship("Incident", back_populates="alerts")
    rule = relationship("AlertRule", back_populates="alerts")
    machine = relationship("Machine", back_populates="alerts")
    service = relationship("Service", back_populates="alerts")
    api_check = relationship("ApiCheck")
