from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional, List
from abc import ABC, abstractmethod

@dataclass
class SnapshotContext:
    incident_id: str
    target_name: str
    config: dict
    evidence_dir: str
    timestamp: datetime
    logger: Any

@dataclass
class CapturedArtifact:
    name: str
    content: str
    status: str  # SUCCESS, FAILED, TIMEOUT
    capture_method: str
    captured_at: datetime
    duration_ms: float
    exit_code: Optional[int] = None
    truncated: bool = False
    bytes_captured: int = 0
    lines_captured: Optional[int] = None
    error_message: Optional[str] = None
    redaction_applied: bool = False

@dataclass
class ProviderCaptureResult:
    provider_name: str
    status: str  # SUCCESS, PARTIAL, FAILED, TIMEOUT
    artifacts: List[CapturedArtifact] = field(default_factory=list)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_ms: float = 0.0
    error_message: Optional[str] = None

class SnapshotProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    def timeout_seconds(self) -> float:
        return 5.0

    @abstractmethod
    def capture(self, context: SnapshotContext) -> Any:
        """
        Captures diagnostic metrics and returns either a raw string or a ProviderCaptureResult.
        """
        pass

@dataclass
class SnapshotResult:
    provider_name: str
    status: str
    execution_time_ms: float
    output_file: str = ""
    error_message: str = ""
