from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from app.evidence import EvidencePackage
from app.collector import CollectorManager

@dataclass
class Incident:
    id: str
    target_name: str
    started_at: str
    status: str = "ACTIVE"
    failure_reason: str = ""
    verification_attempts: int = 0
    evidence: Optional[EvidencePackage] = None

# Encapsulated in-memory storage
_ACTIVE_INCIDENTS: dict[str, Incident] = {}
_DAILY_COUNTERS: dict[str, int] = {}

def _generate_incident_id() -> str:
    """
    Generates a sequential human-readable incident ID: INC-YYYYMMDD-XXXX
    """
    today_str = datetime.now().strftime("%Y%m%d")
    _DAILY_COUNTERS[today_str] = _DAILY_COUNTERS.get(today_str, 0) + 1
    seq_num = _DAILY_COUNTERS[today_str]
    return f"INC-{today_str}-{seq_num:04d}"

def create_incident(target_name: str, failure_reason: str, verification_attempts: int, config: dict) -> Incident:
    """
    Creates a new ACTIVE incident in memory for the target and triggers evidence collection.
    If an incident is already active for this target, returns it instead of creating a duplicate.
    """
    if target_name in _ACTIVE_INCIDENTS:
        return _ACTIVE_INCIDENTS[target_name]
        
    incident_id = _generate_incident_id()
    started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    incident = Incident(
        id=incident_id,
        target_name=target_name,
        started_at=started_at,
        status="ACTIVE",
        failure_reason=failure_reason,
        verification_attempts=verification_attempts
    )
    
    # Store incident first so we can link it
    _ACTIVE_INCIDENTS[target_name] = incident
    
    # Run evidence collection using CollectorManager
    evidence_package = CollectorManager.run(incident_id, target_name, config)
    incident.evidence = evidence_package
    
    # Serialize and persist incident package atomically to disk
    try:
        from app.serializer import serialize_incident
        from app.storage import save_incident_payload
        
        payload = serialize_incident(incident)
        save_incident_payload(incident_id, payload)
    except Exception as e:
        import sys
        print(f"Unexpected serialization block failure: {e}", file=sys.stderr, flush=True)
        
    return incident

def is_incident_active(target_name: str) -> bool:
    """
    Checks if a target has an active incident.
    """
    return target_name in _ACTIVE_INCIDENTS

def get_incident(target_name: str) -> Optional[Incident]:
    """
    Returns the active incident for a target if it exists.
    """
    return _ACTIVE_INCIDENTS.get(target_name)
