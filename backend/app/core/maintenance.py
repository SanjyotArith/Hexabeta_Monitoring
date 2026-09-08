"""
HexaAgent — Maintenance Mode Engine (Phase 2B).

Manages maintenance status, enabling/disabling it thread-safely in-memory.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("hexa_agent.maintenance")

class MaintenanceManager:
    """Manages the in-memory maintenance mode flag."""
    
    def __init__(self) -> None:
        self._enabled: bool = False

    @property
    def is_enabled(self) -> bool:
        """Check if maintenance mode is enabled."""
        return self._enabled

    def enable(self) -> None:
        """Enable maintenance mode."""
        if not self._enabled:
            self._enabled = True
            logger.info("Maintenance mode ENABLED.")

    def disable(self) -> None:
        """Disable maintenance mode."""
        if self._enabled:
            self._enabled = False
            logger.info("Maintenance mode DISABLED.")

maintenance_manager = MaintenanceManager()
