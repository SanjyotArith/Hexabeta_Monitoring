from dataclasses import dataclass
from typing import Any, Optional

@dataclass
class CollectorResult:
    collector_name: str
    success: bool
    started_at: str
    finished_at: str
    duration_ms: float
    data: Optional[Any]
    error: Optional[str]

@dataclass
class EvidencePackage:
    incident_id: str
    target_name: str
    collected_at: str
    collector_results: list[CollectorResult]
