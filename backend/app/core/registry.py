"""
HexaAgent — Collector Registry.

Provides the BaseCollector ABC and a plug-and-play registry.
New collectors register themselves; the API layer calls collect_all().
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger("hexa_agent.registry")


class BaseCollector(ABC):
    """
    Abstract base class every collector must inherit from.

    Subclasses implement ``collect()`` which returns a plain dict
    of raw numeric values.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Short key used in the API response (e.g. 'cpu', 'memory')."""
        ...

    @abstractmethod
    async def collect(self) -> dict[str, Any]:
        """Gather and return metrics as a dict of raw values."""
        ...


class CollectorRegistry:
    """
    Central registry that holds all active collectors.

    Usage::

        registry = CollectorRegistry()
        registry.register(CpuCollector())
        data = await registry.collect_all()
    """

    def __init__(self) -> None:
        self._collectors: dict[str, BaseCollector] = {}

    def register(self, collector: BaseCollector) -> None:
        """Register a collector instance. Overwrites if name already exists."""
        logger.info("Registering collector: %s", collector.name)
        self._collectors[collector.name] = collector

    def unregister(self, name: str) -> None:
        """Remove a collector by name."""
        self._collectors.pop(name, None)
        logger.info("Unregistered collector: %s", name)

    @property
    def registered(self) -> list[str]:
        """Return the names of all registered collectors."""
        return list(self._collectors.keys())

    async def collect_all(self) -> dict[str, dict[str, Any]]:
        """
        Run every registered collector and return an aggregated dict.

        Returns a dict keyed by collector name, e.g.::

            {
                "cpu": {"cpu_percent": 12.3},
                "memory": {"memory_bytes": 123456789, ...},
                ...
            }

        If a single collector fails, its key maps to an error dict and
        other collectors are unaffected.
        """
        results: dict[str, dict[str, Any]] = {}
        for name, collector in self._collectors.items():
            try:
                results[name] = await collector.collect()
            except Exception:
                logger.exception("Collector '%s' failed", name)
                results[name] = {"error": f"Collector '{name}' encountered an error"}
        return results


# Module-level singleton — imported by main.py and the API router.
collector_registry = CollectorRegistry()
