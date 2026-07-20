import sys
from typing import Optional
from app.incident import Incident, create_incident, is_incident_active
from app.snapshot.engine import SnapshotEngine

class IncidentWorkflow:
    """
    Coordinates lifecycle workflows when incidents occur:
    1. Triggers baseline incident creation, diagnostics gathering, and alerts.
    2. Runs the Snapshot Engine to capture volatile machine evidence.
    """
    @classmethod
    def trigger_created(
        cls,
        target_name: str,
        failure_reason: str,
        verification_attempts: int,
        config: dict,
        notifier=None,
        endpoint: Optional[str] = None
    ) -> Incident:
        # Check if an incident is already active for this target
        was_active = is_incident_active(target_name)
        
        # Step 1: Create incident (writes incident.json, dispatches telegram alert)
        incident = create_incident(
            target_name=target_name,
            failure_reason=failure_reason,
            verification_attempts=verification_attempts,
            config=config,
            notifier=notifier,
            endpoint=endpoint
        )
        
        # Step 2: Execute Snapshot Engine to capture volatile diagnostics (only for new incidents)
        if not was_active:
            try:
                SnapshotEngine.run(incident.id, target_name, config)
            except Exception as e:
                print(f"Snapshot Engine run failed: {e}", file=sys.stderr, flush=True)
            
        return incident
