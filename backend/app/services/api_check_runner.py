import asyncio
import socket
import ssl
from datetime import datetime, timedelta
from urllib.parse import urlparse
from typing import Optional
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.database import SessionLocal
from app.models.telemetry import ApiCheck, ApiCheckHistory
from app.models.alerting import AlertRule, Incident, Alert

def get_ssl_expiry_days(url: str) -> Optional[int]:
    """
    Connects to the server over a secure socket and extracts the remaining days
    before the SSL certificate expires.
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme != "https":
            return None
        hostname = parsed.hostname
        port = parsed.port or 443
        
        context = ssl.create_default_context()
        with socket.create_connection((hostname, port), timeout=4) as sock:
            with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert = ssock.getpeercert()
                expire_date_str = cert.get('notAfter')
                if not expire_date_str:
                    return None
                # Format: 'May 24 12:00:00 2026 GMT'
                expire_date = datetime.strptime(expire_date_str, '%b %d %H:%M:%S %Y %Z')
                days_left = (expire_date - datetime.utcnow()).days
                return days_left
    except Exception:
        return None


async def run_single_api_check(db: AsyncSession, api_check: ApiCheck):
    """Executes a single synthetic HTTP check and records results in api_check_history."""
    start_time = datetime.utcnow()
    is_up = False
    response_time_ms = None
    status_code = None
    error_message = None
    
    headers = api_check.headers or {}
    if "User-Agent" not in headers:
        headers["User-Agent"] = "HexaMonitor/1.0.0"
        
    async with httpx.AsyncClient(timeout=api_check.timeout_seconds) as client:
        try:
            # Measure request latency
            response = await client.request(
                method=api_check.request_method,
                url=api_check.url,
                headers=headers,
                content=api_check.request_payload,
            )
            
            latency = datetime.utcnow() - start_time
            response_time_ms = int(latency.total_seconds() * 1000)
            status_code = response.status_code
            
            # Evaluate baseline conditions
            status_matches = (status_code == api_check.expected_status_code)
            body_matches = True
            if api_check.expected_response_match:
                body_matches = api_check.expected_response_match in response.text
                
            if status_matches and body_matches:
                is_up = True
            else:
                reasons = []
                if not status_matches:
                    reasons.append(f"Status Code {status_code} != expected {api_check.expected_status_code}")
                if not body_matches:
                    reasons.append("Response content match failed")
                error_message = ", ".join(reasons)
                
        except httpx.RequestError as exc:
            latency = datetime.utcnow() - start_time
            response_time_ms = int(latency.total_seconds() * 1000)
            error_message = f"HTTP request failed: {str(exc)}"
            
    # Run SSL check if Up and is HTTPS
    ssl_days = None
    if is_up and api_check.url.startswith("https"):
        # Run socket SSL checks in a thread pool to prevent blocking the event loop
        ssl_days = await asyncio.to_thread(get_ssl_expiry_days, api_check.url)
        
    # Write to history database
    history_entry = ApiCheckHistory(
        api_check_id=api_check.id,
        timestamp=start_time,
        is_up=is_up,
        response_time_ms=response_time_ms,
        status_code=status_code,
        error_message=error_message
    )
    db.add(history_entry)
    await db.commit()
    
    # Evaluate Alert Rules for this API Check
    await evaluate_api_check_alerts(db, api_check, is_up, response_time_ms, ssl_days)


async def evaluate_api_check_alerts(
    db: AsyncSession,
    api_check: ApiCheck,
    is_up: bool,
    latency_ms: Optional[int],
    ssl_days: Optional[int]
):
    """
    Evaluates alerting rules specifically mapped to API Checks.
    If conditions fail, it creates an active incident and alert record.
    """
    # Fetch active rules for this environment of type 'api_failed' or 'ssl_expiry'
    rules_query = await db.execute(
        select(AlertRule)
        .where(
            (AlertRule.environment_id == api_check.environment_id) &
            (AlertRule.is_active == True) &
            (AlertRule.check_type.in_(["api_failed", "ssl_expiry"]))
        )
    )
    rules = rules_query.scalars().all()
    
    for rule in rules:
        trigger_alert = False
        message = ""
        trigger_value = None
        
        if rule.check_type == "api_failed" and not is_up:
            trigger_alert = True
            message = f"API Check '{api_check.name}' is DOWN. Target URL: {api_check.url}"
            
        elif rule.check_type == "ssl_expiry" and ssl_days is not None:
            if rule.operator == "<" and ssl_days < (rule.threshold_value or 14):
                trigger_alert = True
                trigger_value = float(ssl_days)
                message = f"SSL Certificate for '{api_check.name}' ({api_check.url}) is expiring in {ssl_days} days."
                
        if trigger_alert:
            # Check if there is an active (unresolved) alert for this rule & check
            active_alert_query = await db.execute(
                select(Alert)
                .where((Alert.alert_rule_id == rule.id) & (Alert.api_check_id == api_check.id) & (Alert.resolved_at == None))
            )
            active_alert = active_alert_query.scalars().first()
            
            if not active_alert:
                # Create Incident if not exists
                incident_query = await db.execute(
                    select(Incident)
                    .where((Incident.environment_id == api_check.environment_id) & (Incident.status == "active") & (Incident.title == f"API Alert: {rule.name}"))
                )
                incident = incident_query.scalars().first()
                
                if not incident:
                    incident = Incident(
                        environment_id=api_check.environment_id,
                        title=f"API Alert: {rule.name}",
                        status="active",
                        severity=rule.severity
                    )
                    db.add(incident)
                    await db.commit()
                    await db.refresh(incident)
                    
                # Create Alert linked to Incident
                new_alert = Alert(
                    incident_id=incident.id,
                    alert_rule_id=rule.id,
                    api_check_id=api_check.id,
                    message=message,
                    value_triggered=trigger_value,
                    started_at=datetime.utcnow()
                )
                db.add(new_alert)
                await db.commit()
                print(f"[ALERT TRIGGERED] {message}")
                
        else:
            # Resolve alert if it was active
            active_alert_query = await db.execute(
                select(Alert)
                .where((Alert.alert_rule_id == rule.id) & (Alert.api_check_id == api_check.id) & (Alert.resolved_at == None))
            )
            active_alert = active_alert_query.scalars().first()
            
            if active_alert:
                active_alert.resolved_at = datetime.utcnow()
                await db.commit()
                
                # Check if all alerts in this incident are resolved
                incident_id = active_alert.incident_id
                if incident_id:
                    unresolved_query = await db.execute(
                        select(Alert).where((Alert.incident_id == incident_id) & (Alert.resolved_at == None))
                    )
                    if not unresolved_query.scalars().first():
                        incident_update = await db.execute(
                            select(Incident).where(Incident.id == incident_id)
                        )
                        incident = incident_update.scalars().first()
                        if incident:
                            incident.status = "resolved"
                            incident.resolved_at = datetime.utcnow()
                            await db.commit()
                print(f"[ALERT RESOLVED] API Check: {api_check.name}")
