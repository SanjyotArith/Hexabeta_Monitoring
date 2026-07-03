"""
HexaAgent — Alert Engine (Phase 2B).

Evaluates system resource levels and service health checks against thresholds,
producing active alerts list.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import psutil

from app.core.config import get_settings

logger = logging.getLogger("hexa_agent.alerts")


def evaluate_alerts(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Evaluate collected snapshot data and return a list of active alerts.

    Checks:
    - Service Down/Unhealthy: backend, postgres, redis, nginx, cloudflared
    - Availability: internal and external health checks
    - Resource thresholds: CPU, Memory, Disk, GPU
    """
    settings = get_settings()
    alerts: list[dict[str, Any]] = []

    # Helper to append an alert
    def add_alert(service: str, message: str, severity: str = "critical") -> None:
        alerts.append({
            "service": service,
            "message": message,
            "severity": severity,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    # --- 1. Service Health Alerts ---
    infra = snapshot.get("infrastructure", {})

    # Backend
    backend = infra.get("backend", {})
    if backend:
        if not backend.get("running"):
            add_alert("backend", "HexaBeta backend process is not running")
        elif not backend.get("healthy"):
            add_alert("backend", "HexaBeta backend is running but unhealthy")
        
        # Internal health response time / status
        internal = backend.get("internal_health") or {}
        if internal and not internal.get("healthy"):
            add_alert("backend", f"Backend internal health check failed: {internal.get('error') or 'HTTP ' + str(internal.get('http_status'))}")
        
        # External health response time / status
        external = backend.get("external_health") or {}
        if external and not external.get("healthy"):
            add_alert("backend", f"Backend external health check failed: {external.get('error') or 'HTTP ' + str(external.get('http_status'))}")

    # Postgres
    postgres = infra.get("postgres", {})
    if postgres:
        if not postgres.get("running"):
            add_alert("postgres", "PostgreSQL service is not running")
        elif not postgres.get("healthy") or not postgres.get("connection_test"):
            add_alert("postgres", "PostgreSQL database connection test failed")

    # Redis
    redis = infra.get("redis", {})
    if redis:
        if not redis.get("running"):
            add_alert("redis", "Redis service is not running")
        elif not redis.get("healthy") or not redis.get("ping"):
            add_alert("redis", "Redis ping test failed")

    # Nginx
    nginx = infra.get("nginx", {})
    if nginx:
        if not nginx.get("running"):
            add_alert("nginx", "Nginx web server is not running")
        elif not nginx.get("healthy"):
            add_alert("nginx", "Nginx service check failed (HTTP status not healthy)")

    # Cloudflared
    cloudflared = infra.get("cloudflared", {})
    if cloudflared:
        if not cloudflared.get("running"):
            add_alert("cloudflared", "Cloudflared process is not running")
        elif not cloudflared.get("tunnel_connected"):
            add_alert("cloudflared", f"Cloudflare Tunnel '{settings.CLOUDFLARED_TUNNEL}' is disconnected")

    # --- 2. Availability Alerts ---
    availability = snapshot.get("availability", {})
    if availability:
        internal_avail = availability.get("internal") or {}
        if internal_avail and not internal_avail.get("healthy"):
            add_alert("availability", "Internal health endpoint returned non-healthy response")

        external_avail = availability.get("external") or {}
        if external_avail and not external_avail.get("healthy"):
            add_alert("availability", "External availability check failed (site may be down to external users)")

    # --- 3. Resource Threshold Alerts ---
    # CPU: Check system-wide CPU
    try:
        sys_cpu = psutil.cpu_percent(interval=None)
        if sys_cpu >= settings.ALERT_CPU_THRESHOLD:
            add_alert("system", f"High CPU usage: {sys_cpu}% (threshold: {settings.ALERT_CPU_THRESHOLD}%)", "warning")
    except Exception:
        pass

    # Memory: Check system-wide Memory
    try:
        sys_mem = psutil.virtual_memory().percent
        if sys_mem >= settings.ALERT_MEMORY_THRESHOLD:
            add_alert("system", f"High Memory usage: {sys_mem}% (threshold: {settings.ALERT_MEMORY_THRESHOLD}%)", "warning")
    except Exception:
        pass

    # Disk: Check disk percent from System section of snapshot
    system_sec = snapshot.get("system", {})
    if system_sec:
        disk_pct = system_sec.get("disk_percent")
        if disk_pct is not None and disk_pct >= settings.ALERT_DISK_THRESHOLD:
            add_alert("system", f"High Disk usage on project volume: {disk_pct}% (threshold: {settings.ALERT_DISK_THRESHOLD}%)", "warning")

    # GPU: Check GPU utilization if available
    resources = snapshot.get("resources", {})
    if resources:
        gpu = resources.get("gpu", {})
        if gpu:
            gpu_util = gpu.get("utilization")
            if gpu_util is not None and gpu_util >= settings.ALERT_GPU_THRESHOLD:
                add_alert("gpu", f"High GPU utilization: {gpu_util}% (threshold: {settings.ALERT_GPU_THRESHOLD}%)", "warning")

    return alerts
