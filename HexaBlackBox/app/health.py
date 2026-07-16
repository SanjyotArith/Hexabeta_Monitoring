from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Optional, Dict

@dataclass
class ComponentHealth:
    name: str
    status: str = "HEALTHY"
    last_heartbeat: Optional[datetime] = None
    last_success: Optional[datetime] = None
    last_failure: Optional[datetime] = None
    failure_reason: Optional[str] = None
    consecutive_failures: int = 0

class RuntimeHealthManager:
    """
    Coordinates and tracks in-memory health metrics of HexaBlackBox subsystems.
    """
    def __init__(self) -> None:
        self._components: Dict[str, ComponentHealth] = {}

    def register_component(self, name: str) -> None:
        """
        Registers a new component to be tracked by the manager.
        """
        if name not in self._components:
            self._components[name] = ComponentHealth(name=name)

    def heartbeat(self, name: str) -> None:
        """
        Updates the heartbeat timestamp for a registered component.
        """
        if name in self._components:
            self._components[name].last_heartbeat = datetime.now(timezone.utc)

    def mark_success(self, name: str) -> None:
        """
        Updates timestamps, status, and resets consecutive failure counters on success.
        """
        if name in self._components:
            comp = self._components[name]
            now = datetime.now(timezone.utc)
            comp.status = "HEALTHY"
            comp.last_success = now
            comp.consecutive_failures = 0
            comp.failure_reason = None

    def mark_failure(self, name: str, reason: str) -> None:
        """
        Records consecutive failures, failure timestamps, and updates status to UNHEALTHY.
        """
        if name in self._components:
            comp = self._components[name]
            now = datetime.now(timezone.utc)
            comp.status = "UNHEALTHY"
            comp.last_failure = now
            comp.failure_reason = reason
            comp.consecutive_failures += 1

    def get_health(self, name: str) -> Optional[ComponentHealth]:
        """
        Returns a defensive copy of a component's health status.
        """
        if name in self._components:
            # Returns a read-only copy of the dataclass to prevent direct mutability of state
            return replace(self._components[name])
        return None
