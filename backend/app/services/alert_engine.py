from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.infrastructure import Machine, Service
from app.models.telemetry import MachineMetric
from app.models.alerting import AlertRule, Incident, Alert
from app.services.notifier import send_slack_notification

async def evaluate_machine_metrics_alerts(db: AsyncSession, machine_id: int, metrics: MachineMetric):
    """
    Evaluates metric rules (CPU, RAM, Disk, Temperature, Load) for a host.
    Creates incidents and triggers Slack notifications when values cross thresholds.
    """
    # Fetch environment of the machine
    machine_res = await db.execute(select(Machine).where(Machine.id == machine_id))
    machine = machine_res.scalars().first()
    if not machine:
        return
        
    env_id = machine.environment_id
    
    # Query active alert rules of type 'metric_threshold' for this environment
    rules_res = await db.execute(
        select(AlertRule)
        .where((AlertRule.environment_id == env_id) & (AlertRule.is_active == True) & (AlertRule.check_type == "metric_threshold"))
    )
    rules = rules_res.scalars().all()
    
    for rule in rules:
        value = None
        
        # Extract the comparison value based on the rule configuration
        if rule.metric_name == "cpu_usage":
            value = metrics.cpu_usage
        elif rule.metric_name == "ram_percent" and metrics.ram_total_bytes > 0:
            value = (metrics.ram_used_bytes / metrics.ram_total_bytes) * 100.0
        elif rule.metric_name == "disk_percent" and metrics.disk_total_bytes > 0:
            value = (metrics.disk_used_bytes / metrics.disk_total_bytes) * 100.0
        elif rule.metric_name == "temperature_celsius":
            value = metrics.temperature_celsius
        elif rule.metric_name == "load_avg_1m":
            value = metrics.load_avg_1m
            
        if value is None:
            continue
            
        trigger_alert = False
        if rule.operator == ">" and value > rule.threshold_value:
            trigger_alert = True
        elif rule.operator == "<" and value < rule.threshold_value:
            trigger_alert = True
        elif rule.operator == "==" and value == rule.threshold_value:
            trigger_alert = True
            
        if trigger_alert:
            # Check if there is an active alert for this rule & machine
            active_res = await db.execute(
                select(Alert)
                .where((Alert.alert_rule_id == rule.id) & (Alert.machine_id == machine_id) & (Alert.resolved_at == None))
            )
            active_alert = active_res.scalars().first()
            
            if not active_alert:
                # Create Incident
                inc_res = await db.execute(
                    select(Incident)
                    .where((Incident.environment_id == env_id) & (Incident.status == "active") & (Incident.title == f"Metric Alert: {rule.name}"))
                )
                incident = inc_res.scalars().first()
                if not incident:
                    incident = Incident(
                        environment_id=env_id,
                        title=f"Metric Alert: {rule.name}",
                        status="active",
                        severity=rule.severity
                    )
                    db.add(incident)
                    await db.commit()
                    await db.refresh(incident)
                    
                message = f"Host '{machine.name}' crossed threshold: {rule.metric_name} is {value:.1f} (Rule: {rule.operator} {rule.threshold_value})"
                
                new_alert = Alert(
                    incident_id=incident.id,
                    alert_rule_id=rule.id,
                    machine_id=machine_id,
                    message=message,
                    value_triggered=value,
                    started_at=datetime.utcnow()
                )
                db.add(new_alert)
                await db.commit()
                
                # Dispatch notification
                await send_slack_notification(db, message, rule.severity)
        else:
            # Resolve alert if it was active
            active_res = await db.execute(
                select(Alert)
                .where((Alert.alert_rule_id == rule.id) & (Alert.machine_id == machine_id) & (Alert.resolved_at == None))
            )
            active_alert = active_res.scalars().first()
            if active_alert:
                active_alert.resolved_at = datetime.utcnow()
                await db.commit()
                
                message = f"RESOLVED: Host '{machine.name}' metric '{rule.metric_name}' is back to normal: {value:.1f}."
                await send_slack_notification(db, message, "info")
                
                # Auto-resolve Incident if all associated alerts are resolved
                incident_id = active_alert.incident_id
                if incident_id:
                    unresolved_query = await db.execute(
                        select(Alert).where((Alert.incident_id == incident_id) & (Alert.resolved_at == None))
                    )
                    if not unresolved_query.scalars().first():
                        inc_update = await db.execute(select(Incident).where(Incident.id == incident_id))
                        incident = inc_update.scalars().first()
                        if incident:
                            incident.status = "resolved"
                            incident.resolved_at = datetime.utcnow()
                            await db.commit()


async def evaluate_service_status_alerts(db: AsyncSession, service: Service, status: str):
    """
    Evaluates process rules for launchd, Postgres, MongoDB, Nginx.
    Triggers critical incidents if services enter a stopped or failed state.
    """
    # Fetch environment of the service
    machine_res = await db.execute(select(Machine).where(Machine.id == service.machine_id))
    machine = machine_res.scalars().first()
    if not machine:
        return
        
    env_id = machine.environment_id
    
    # Query active alert rules of type 'service_down' for this environment
    rules_res = await db.execute(
        select(AlertRule)
        .where((AlertRule.environment_id == env_id) & (AlertRule.is_active == True) & (AlertRule.check_type == "service_down"))
    )
    rules = rules_res.scalars().all()
    
    for rule in rules:
        trigger_alert = (status in ["failed", "stopped"])
        
        if trigger_alert:
            # Check for unresolved alert
            active_res = await db.execute(
                select(Alert)
                .where((Alert.alert_rule_id == rule.id) & (Alert.service_id == service.id) & (Alert.resolved_at == None))
            )
            active_alert = active_res.scalars().first()
            
            if not active_alert:
                inc_res = await db.execute(
                    select(Incident)
                    .where((Incident.environment_id == env_id) & (Incident.status == "active") & (Incident.title == f"Service Alert: {service.name} Down"))
                )
                incident = inc_res.scalars().first()
                if not incident:
                    incident = Incident(
                        environment_id=env_id,
                        title=f"Service Alert: {service.name} Down",
                        status="active",
                        severity=rule.severity
                    )
                    db.add(incident)
                    await db.commit()
                    await db.refresh(incident)
                    
                message = f"Service '{service.name}' on Host '{machine.name}' has entered status: {status.upper()}!"
                new_alert = Alert(
                    incident_id=incident.id,
                    alert_rule_id=rule.id,
                    service_id=service.id,
                    message=message,
                    started_at=datetime.utcnow()
                )
                db.add(new_alert)
                await db.commit()
                
                await send_slack_notification(db, message, rule.severity)
        else:
            # Recover/Resolve alert if it was active
            active_res = await db.execute(
                select(Alert)
                .where((Alert.alert_rule_id == rule.id) & (Alert.service_id == service.id) & (Alert.resolved_at == None))
            )
            active_alert = active_res.scalars().first()
            
            if active_alert:
                active_alert.resolved_at = datetime.utcnow()
                await db.commit()
                
                message = f"RESOLVED: Service '{service.name}' on Host '{machine.name}' is back to {status.upper()}."
                await send_slack_notification(db, message, "info")
                
                incident_id = active_alert.incident_id
                if incident_id:
                    unresolved_query = await db.execute(
                        select(Alert).where((Alert.incident_id == incident_id) & (Alert.resolved_at == None))
                    )
                    if not unresolved_query.scalars().first():
                        inc_update = await db.execute(select(Incident).where(Incident.id == incident_id))
                        incident = inc_update.scalars().first()
                        if incident:
                            incident.status = "resolved"
                            incident.resolved_at = datetime.utcnow()
                            await db.commit()
