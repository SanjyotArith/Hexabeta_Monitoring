from dataclasses import dataclass
from datetime import datetime
from typing import Any
from abc import ABC, abstractmethod

@dataclass
class SnapshotContext:
    incident_id: str
    target_name: str
    config: dict
    evidence_dir: str
    timestamp: datetime
    logger: Any

class SnapshotProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    def timeout_seconds(self) -> float:
        return 5.0

    @abstractmethod
    def capture(self, context: SnapshotContext) -> str:
        """
        Captures diagnostic metrics and returns the raw string content.
        """
        pass

@dataclass
class SnapshotResult:
    provider_name: str
    status: str
    execution_time_ms: float
    output_file: str = ""
    error_message: str = ""
