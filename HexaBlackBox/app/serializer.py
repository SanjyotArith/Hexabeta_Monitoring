import dataclasses
from datetime import datetime
from typing import Any, Dict

def serialize_collector_result(res) -> Dict[str, Any]:
    if res is None:
        return None
    return {
        "collector_name": res.collector_name,
        "success": res.success,
        "started_at": res.started_at,
        "finished_at": res.finished_at,
        "duration_ms": res.duration_ms,
        "data": res.data,
        "error": res.error
    }

def serialize_evidence_package(pkg) -> Dict[str, Any]:
    if pkg is None:
        return None
    return {
        "incident_id": pkg.incident_id,
        "target_name": pkg.target_name,
        "collected_at": pkg.collected_at,
        "collector_results": [serialize_collector_result(r) for r in pkg.collector_results]
    }

def serialize_incident(incident) -> Dict[str, Any]:
    if incident is None:
        return None
        
    evidence_serialized = serialize_evidence_package(incident.evidence)
    
    # Calculate execution summary statistics
    total_executed = 0
    total_succeeded = 0
    total_failed = 0
    total_duration = 0.0
    
    if incident.evidence and incident.evidence.collector_results:
        total_executed = len(incident.evidence.collector_results)
        for res in incident.evidence.collector_results:
            if res.success:
                total_succeeded += 1
            else:
                total_failed += 1
            total_duration += res.duration_ms
            
    metadata = {
        "schema_version": 1,
        "persisted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_collectors_executed": total_executed,
        "total_collectors_succeeded": total_succeeded,
        "total_collectors_failed": total_failed,
        "total_collection_duration_ms": round(total_duration, 2)
    }
    
    return {
        "incident_id": incident.id,
        "target_name": incident.target_name,
        "started_at": incident.started_at,
        "status": incident.status,
        "failure_reason": incident.failure_reason,
        "verification_attempts": incident.verification_attempts,
        "evidence": evidence_serialized,
        "metadata": metadata
    }
