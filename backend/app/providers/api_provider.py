"""
HexaAgent — API Metrics Provider (Phase 3 — Read-Only Consumer).

Reads API observability data from the HexaBeta Backend database
and exposes it through the collector/provider architecture.
"""

from __future__ import annotations

from typing import Any
from app.core.registry import BaseCollector
from app.core.api_observability import api_observability_reader


class ApiProvider(BaseCollector):
    @property
    def name(self) -> str:
        return "api"

    async def collect(self) -> dict[str, Any]:
        return api_observability_reader.get_metrics()
