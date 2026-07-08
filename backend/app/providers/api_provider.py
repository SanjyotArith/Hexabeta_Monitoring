"""
HexaAgent — API Metrics Provider (Phase 3).
"""

from __future__ import annotations

from typing import Any
from app.core.registry import BaseCollector
from app.core.api_observability import api_observability_engine

class ApiProvider(BaseCollector):
    @property
    def name(self) -> str:
        return "api"

    async def collect(self) -> dict[str, Any]:
        return api_observability_engine.get_metrics()
