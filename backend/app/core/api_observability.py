"""
HexaAgent — API Observability Reader (Phase 3 — Read-Only Consumer).

Reads the API observability database produced by HexaBeta Backend.
HexaAgent is a READ-ONLY consumer; all API observability data is
produced by HexaBeta Backend and stored at:

    Path(settings.HEXABETA_BACKEND_PATH) / "data" / "api_observability.db"

This module aggregates endpoint_registry, request_metrics, failures,
dependency_metrics, uploads, authentication, and worker_statistics
into the snapshot format consumed by HexaMonitor.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import psutil

logger = logging.getLogger("hexa_agent.api_observability")


class ApiObservabilityReader:
    """
    Read-only consumer of the HexaBeta Backend API observability database.

    Opens the backend's api_observability.db in read-only mode and
    aggregates data for the HexaAgent snapshot endpoint.
    """

    def __init__(self) -> None:
        from app.core.config import get_settings
        settings = get_settings()
        self.db_path = Path(settings.HEXABETA_BACKEND_PATH) / "data" / "api_observability.db"
        self._peak_rps: float = 0.0
        logger.info(
            "ApiObservabilityReader initialized — reading from: %s",
            self.db_path,
        )

    def _open_readonly(self) -> sqlite3.Connection:
        """Open the backend observability database in read-only mode."""
        uri = f"file:{self.db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    def get_metrics(self) -> dict[str, Any]:
        """Aggregate metrics from the backend's SQLite database (read-only)."""
        now = datetime.now(timezone.utc)
        ten_sec_ago = (now - timedelta(seconds=10)).isoformat()

        summary = {
            "requests_per_second": 0.0,
            "active_requests": 0,
            "total_requests": 0,
            "peak_rps": 0.0,
            "success_count": 0,
            "failure_count": 0,
            "avg_latency": 0.0,
            "min_latency": 0.0,
            "max_latency": 0.0,
            "p95_latency": 0.0,
            "p99_latency": 0.0,
        }

        status_codes = {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0}
        endpoints: List[Dict[str, Any]] = []
        slow_endpoints: List[Dict[str, Any]] = []
        exceptions: List[Dict[str, Any]] = []
        dependencies: List[Dict[str, Any]] = []
        background_tasks: List[Dict[str, Any]] = []
        uploads = {
            "image_uploads_count": 0,
            "document_uploads_count": 0,
            "avg_upload_time_ms": 0.0,
            "largest_upload_bytes": 0,
            "failed_uploads_count": 0,
        }
        authentication = {
            "successful_logins": 0,
            "failed_logins": 0,
            "expired_tokens": 0,
            "invalid_tokens": 0,
        }

        if not self.db_path.exists():
            logger.warning(
                "Backend observability database not found at %s — returning empty metrics",
                self.db_path,
            )
            return self._build_response(
                summary, status_codes, endpoints, slow_endpoints,
                exceptions, dependencies, background_tasks, uploads,
                authentication,
            )

        try:
            with self._open_readonly() as conn:
                # 1. Fetch all discovered routes from endpoint_registry
                cursor = conn.execute("SELECT route, method FROM endpoint_registry")
                registered = [(r["route"], r["method"]) for r in cursor.fetchall()]

                # 2. Fetch all requests (request_metrics table — fallback to 'requests')
                requests_table = self._detect_table(conn, "request_metrics", "requests")
                cursor = conn.execute(
                    f"SELECT route, method, status_code, processing_time, timestamp FROM {requests_table}"
                )
                raw_reqs = cursor.fetchall()

                # 3. Fetch active requests per endpoint
                if self._table_exists(conn, "worker_endpoint_active"):
                    cursor = conn.execute(
                        "SELECT route, method, sum(active_requests) as active "
                        "FROM worker_endpoint_active GROUP BY route, method"
                    )
                    active_endpoint_map = {
                        (r["route"], r["method"]): max(0, r["active"])
                        for r in cursor.fetchall()
                    }
                else:
                    active_endpoint_map = {}

                # 4. Fetch failures
                cursor = conn.execute(
                    """
                    SELECT route, method, timestamp, status_code, exception_type,
                           exception_message, failure_reason, stack_trace, worker_pid
                    FROM failures
                    """
                )
                failures_raw = cursor.fetchall()

                # Global summary metrics
                cursor = conn.execute(
                    f"""
                    SELECT
                        count(*) as total,
                        sum(case when status_code >= 200 and status_code < 400 then 1 else 0 end) as success,
                        sum(case when status_code >= 400 or exception_type is not null then 1 else 0 end) as failure,
                        avg(processing_time) as avg_lat,
                        min(processing_time) as min_lat,
                        max(processing_time) as max_lat
                    FROM {requests_table}
                    """
                )
                row = cursor.fetchone()
                if row and row["total"] > 0:
                    summary["total_requests"] = row["total"]
                    summary["success_count"] = row["success"] or 0
                    summary["failure_count"] = row["failure"] or 0
                    summary["avg_latency"] = round(row["avg_lat"] or 0.0, 2)
                    summary["min_latency"] = round(row["min_lat"] or 0.0, 2)
                    summary["max_latency"] = round(row["max_lat"] or 0.0, 2)

                cursor = conn.execute(
                    f"SELECT processing_time FROM {requests_table} ORDER BY processing_time ASC"
                )
                latencies = [r["processing_time"] for r in cursor.fetchall()]
                if latencies:
                    n = len(latencies)
                    summary["p95_latency"] = round(latencies[int(n * 0.95)], 2)
                    summary["p99_latency"] = round(latencies[int(n * 0.99)], 2)

                # Status Codes
                cursor = conn.execute(
                    f"SELECT status_code, count(*) as cnt FROM {requests_table} GROUP BY status_code"
                )
                for r in cursor.fetchall():
                    sc = r["status_code"]
                    cnt = r["cnt"]
                    if 200 <= sc < 300:
                        status_codes["2xx"] += cnt
                    elif 300 <= sc < 400:
                        status_codes["3xx"] += cnt
                    elif 400 <= sc < 500:
                        status_codes["4xx"] += cnt
                    elif 500 <= sc:
                        status_codes["5xx"] += cnt

                # RPS
                cursor = conn.execute(
                    f"SELECT count(*) as cnt FROM {requests_table} WHERE timestamp >= ?",
                    (ten_sec_ago,),
                )
                ten_sec_count = cursor.fetchone()["cnt"]
                current_rps = round(ten_sec_count / 10.0, 2)
                summary["requests_per_second"] = current_rps
                if current_rps > self._peak_rps:
                    self._peak_rps = current_rps
                summary["peak_rps"] = self._peak_rps

                # Active requests from worker_stats
                if self._table_exists(conn, "worker_stats"):
                    cursor = conn.execute(
                        "SELECT sum(active_requests) as active FROM worker_stats"
                    )
                    row = cursor.fetchone()
                    summary["active_requests"] = (row["active"] or 0) if row else 0
                else:
                    # Fallback: sum from worker_endpoint_active
                    summary["active_requests"] = sum(active_endpoint_map.values())

                # Grouping requests & failures in Python
                req_groups: Dict[tuple, list] = defaultdict(list)
                for r in raw_reqs:
                    req_groups[(r["route"], r["method"])].append(r)

                fail_groups: Dict[tuple, list] = defaultdict(list)
                for f in failures_raw:
                    fail_groups[(f["route"], f["method"])].append(f)

                # Per-endpoint calculations
                all_endpoints = set(registered) | set(req_groups.keys())
                for route, method in all_endpoints:
                    reqs = req_groups[(route, method)]
                    fails = fail_groups[(route, method)]

                    total_reqs = len(reqs)
                    active = active_endpoint_map.get((route, method), 0)

                    # Compute per-endpoint RPS
                    ept_ten_sec = sum(1 for r in reqs if r["timestamp"] >= ten_sec_ago)
                    ept_rps = round(ept_ten_sec / 10.0, 2)

                    success_cnt = sum(1 for r in reqs if 200 <= r["status_code"] < 400)
                    failure_cnt = total_reqs - success_cnt

                    success_rate = 100.0
                    failure_rate = 0.0
                    if total_reqs > 0:
                        success_rate = round((success_cnt / total_reqs) * 100, 2)
                        failure_rate = round((failure_cnt / total_reqs) * 100, 2)

                    avg_l = min_l = max_l = p95_l = p99_l = 0.0
                    last_called = None
                    last_status = None

                    if total_reqs > 0:
                        lats = sorted([r["processing_time"] for r in reqs])
                        avg_l = round(sum(lats) / total_reqs, 2)
                        min_l = round(lats[0], 2)
                        max_l = round(lats[-1], 2)
                        p95_l = round(lats[int(total_reqs * 0.95)], 2)
                        p99_l = round(lats[int(total_reqs * 0.99)], 2)

                        sorted_reqs = sorted(reqs, key=lambda x: x["timestamp"], reverse=True)
                        last_called = sorted_reqs[0]["timestamp"]
                        last_status = sorted_reqs[0]["status_code"]

                    # Health Status logic
                    health_status = "healthy"
                    if failure_rate > 10.0 or avg_l > 3000:
                        health_status = "critical"
                    elif failure_rate > 2.0 or avg_l > 1000 or p95_l > 2000:
                        health_status = "warning"

                    # Failure History
                    last_failure_time = None
                    most_common_failure = None
                    latest_exception = None
                    latest_error_message = None
                    latest_fail_info = None

                    if fails:
                        sorted_fails = sorted(fails, key=lambda x: x["timestamp"], reverse=True)
                        last_failure_time = sorted_fails[0]["timestamp"]
                        latest_exception = sorted_fails[0]["exception_type"]
                        latest_error_message = sorted_fails[0]["exception_message"]

                        reasons = [f["failure_reason"] for f in fails if f["failure_reason"]]
                        if reasons:
                            most_common_failure = max(set(reasons), key=reasons.count)

                        latest_fail_info = {
                            "timestamp": last_failure_time,
                            "status_code": sorted_fails[0]["status_code"],
                            "exception_type": latest_exception,
                            "exception_message": latest_error_message,
                            "failure_reason": sorted_fails[0]["failure_reason"],
                            "stack_trace": sorted_fails[0]["stack_trace"],
                            "worker_pid": sorted_fails[0]["worker_pid"],
                        }

                    # Route status code distribution
                    route_sc = {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0}
                    for r in reqs:
                        sc = r["status_code"]
                        if 200 <= sc < 300:
                            route_sc["2xx"] += 1
                        elif 300 <= sc < 400:
                            route_sc["3xx"] += 1
                        elif 400 <= sc < 500:
                            route_sc["4xx"] += 1
                        elif 500 <= sc:
                            route_sc["5xx"] += 1

                    endpoints.append({
                        "route": route,
                        "method": method,
                        "total_requests": total_reqs,
                        "requests_per_second": ept_rps,
                        "active_requests": active,
                        "success_count": success_cnt,
                        "failure_count": failure_cnt,
                        "success_rate": success_rate,
                        "failure_rate": failure_rate,
                        "avg_latency": avg_l,
                        "min_latency": min_l,
                        "max_latency": max_l,
                        "p95": p95_l,
                        "p99": p99_l,
                        "last_called": last_called,
                        "last_status_code": last_status,
                        "health_status": health_status,
                        "latest_failure_information": latest_fail_info,
                        "latest_exception": latest_exception,
                        "latest_error_message": latest_error_message,
                        "failure_history": {
                            "last_failure_time": last_failure_time,
                            "failure_count": len(fails),
                            "most_common_failure": most_common_failure,
                            "latest_exception": latest_exception,
                            "latest_error_message": latest_error_message,
                        } if fails else None,
                        "status_codes": route_sc,
                    })

                # Slow endpoints (latency >= 500ms)
                cursor = conn.execute(
                    f"""
                    SELECT route, method, processing_time, timestamp, status_code
                    FROM {requests_table}
                    WHERE processing_time >= 500
                    ORDER BY processing_time DESC
                    LIMIT 10
                    """
                )
                for r in cursor.fetchall():
                    lat = r["processing_time"]
                    slow_endpoints.append({
                        "route": r["route"],
                        "method": r["method"],
                        "latency": round(lat, 2),
                        "timestamp": r["timestamp"],
                        "status_code": r["status_code"],
                        "severity": "Critical" if lat >= 3000 else "High" if lat >= 1000 else "Warning",
                    })

                # Exception Analytics
                cursor = conn.execute(
                    f"""
                    SELECT exception_type, route, method, count(*) as cnt, max(timestamp) as latest
                    FROM {requests_table}
                    WHERE exception_type IS NOT NULL
                    GROUP BY exception_type, route, method
                    """
                )
                for r in cursor.fetchall():
                    exceptions.append({
                        "exception_name": r["exception_type"],
                        "endpoint": r["route"],
                        "method": r["method"],
                        "frequency": r["cnt"],
                        "latest_occurrence": r["latest"],
                    })

                # Dependency Monitoring
                dep_table = self._detect_table(conn, "dependency_metrics", "dependency_calls")
                cursor = conn.execute(
                    f"""
                    SELECT name, count(*) as total,
                           sum(success) as success_cnt,
                           sum(1 - success) as failure_cnt,
                           avg(latency_ms) as avg_lat,
                           min(latency_ms) as min_lat,
                           max(latency_ms) as max_lat
                    FROM {dep_table}
                    GROUP BY name
                    """
                )
                for r in cursor.fetchall():
                    dependencies.append({
                        "name": r["name"],
                        "total_calls": r["total"],
                        "success_count": r["success_cnt"] or 0,
                        "failure_count": r["failure_cnt"] or 0,
                        "avg_latency": round(r["avg_lat"] or 0.0, 2),
                        "min_latency": round(r["min_lat"] or 0.0, 2),
                        "max_latency": round(r["max_lat"] or 0.0, 2),
                    })

                # Background Task Monitoring
                if self._table_exists(conn, "background_tasks"):
                    cursor = conn.execute(
                        """
                        SELECT task_name,
                               sum(case when status = 'running' then 1 else 0 end) as running,
                               sum(case when status = 'completed' then 1 else 0 end) as completed,
                               sum(case when status = 'failed' then 1 else 0 end) as failed,
                               avg(execution_time) as avg_exec
                        FROM background_tasks
                        GROUP BY task_name
                        """
                    )
                    for r in cursor.fetchall():
                        background_tasks.append({
                            "task_name": r["task_name"],
                            "running_count": r["running"] or 0,
                            "completed_count": r["completed"] or 0,
                            "failed_count": r["failed"] or 0,
                            "avg_execution_time": round(r["avg_exec"] or 0.0, 2) if r["avg_exec"] else 0.0,
                        })

                # Upload Monitoring
                upload_table = self._detect_table(conn, "uploads", "upload_events")
                cursor = conn.execute(
                    f"""
                    SELECT upload_type, count(*) as total,
                           sum(case when success = 0 then 1 else 0 end) as failed,
                           avg(latency_ms) as avg_lat,
                           max(size_bytes) as max_size
                    FROM {upload_table}
                    GROUP BY upload_type
                    """
                )
                total_uploads = 0
                total_upload_time = 0.0
                for r in cursor.fetchall():
                    ut = r["upload_type"]
                    total_uploads += r["total"]
                    total_upload_time += (r["avg_lat"] or 0.0) * r["total"]
                    uploads["failed_uploads_count"] += r["failed"] or 0
                    if r["max_size"] and r["max_size"] > uploads["largest_upload_bytes"]:
                        uploads["largest_upload_bytes"] = r["max_size"]

                    if ut == "image":
                        uploads["image_uploads_count"] = r["total"]
                    else:
                        uploads["document_uploads_count"] = r["total"]

                if total_uploads > 0:
                    uploads["avg_upload_time_ms"] = round(total_upload_time / total_uploads, 2)

                # Authentication Analytics
                auth_table = self._detect_table(conn, "authentication", "auth_events")
                cursor = conn.execute(
                    f"SELECT event_type, count(*) as cnt FROM {auth_table} GROUP BY event_type"
                )
                for r in cursor.fetchall():
                    et = r["event_type"]
                    cnt = r["cnt"]
                    if et == "login_success":
                        authentication["successful_logins"] = cnt
                    elif et == "login_failure":
                        authentication["failed_logins"] = cnt
                    elif et == "token_expired":
                        authentication["expired_tokens"] = cnt
                    elif et == "token_invalid":
                        authentication["invalid_tokens"] = cnt

        except Exception as e:
            logger.error("Error reading backend observability database: %s", e)

        # Worker Details (psutil runtime mapping)
        workers_info = self._get_backend_workers()
        worker_details: List[Dict[str, Any]] = []
        db_pids: set = set()
        try:
            if self.db_path.exists():
                with self._open_readonly() as conn:
                    if self._table_exists(conn, "worker_stats"):
                        cursor = conn.execute(
                            "SELECT pid, handled_requests, active_requests FROM worker_stats"
                        )
                        for r in cursor.fetchall():
                            db_pids.add(r["pid"])
                            matching = next((w for w in workers_info if w["pid"] == r["pid"]), None)
                            worker_details.append({
                                "pid": r["pid"],
                                "cpu_percent": matching["cpu_percent"] if matching else 0.0,
                                "memory_mb": matching["memory_mb"] if matching else 0.0,
                                "handled_requests": r["handled_requests"],
                                "active_requests": r["active_requests"],
                            })
        except Exception:
            pass

        active_pids = {w["pid"] for w in workers_info}
        restart_count = max(0, len(db_pids - active_pids))

        workers_data = {
            "active_workers_count": len(workers_info),
            "restart_count": restart_count,
            "worker_details": worker_details,
        }

        return self._build_response(
            summary, status_codes, endpoints, slow_endpoints,
            exceptions, dependencies, background_tasks, uploads,
            authentication, workers_data,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _table_exists(self, conn: sqlite3.Connection, name: str) -> bool:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        )
        return cursor.fetchone() is not None

    def _detect_table(self, conn: sqlite3.Connection, preferred: str, fallback: str) -> str:
        """Return preferred table name if it exists, else fallback."""
        if self._table_exists(conn, preferred):
            return preferred
        return fallback

    def _get_backend_workers(self) -> List[Dict[str, Any]]:
        """Discover HexaBeta backend (uvicorn/gunicorn) worker processes."""
        workers: List[Dict[str, Any]] = []
        try:
            for proc in psutil.process_iter(["pid", "name", "cmdline"]):
                try:
                    cmdline = " ".join(proc.info.get("cmdline") or []).lower()
                    name = (proc.info.get("name") or "").lower()
                    # Match backend uvicorn/gunicorn workers
                    if ("uvicorn" in cmdline or "gunicorn" in cmdline) and (
                        "app.main" in cmdline or "main:app" in cmdline
                    ):
                        # Exclude HexaAgent's own process
                        if "hexa_agent" not in cmdline and "9000" not in cmdline:
                            cpu = proc.cpu_percent(interval=None)
                            mem_mb = round(proc.memory_info().rss / (1024 * 1024), 2)
                            workers.append({
                                "pid": proc.pid,
                                "cpu_percent": cpu,
                                "memory_mb": mem_mb,
                            })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception as e:
            logger.error("Failed to gather backend worker processes: %s", e)
        return workers

    def _build_response(
        self,
        summary: Dict[str, Any],
        status_codes: Dict[str, int],
        endpoints: List[Dict[str, Any]],
        slow_endpoints: List[Dict[str, Any]],
        exceptions: List[Dict[str, Any]],
        dependencies: List[Dict[str, Any]],
        background_tasks: List[Dict[str, Any]],
        uploads: Dict[str, Any],
        authentication: Dict[str, Any],
        workers_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build the final metrics response (same contract as before)."""
        if workers_data is None:
            workers_data = {
                "active_workers_count": 0,
                "restart_count": 0,
                "worker_details": [],
            }

        health_score, alerts = self._compute_health_score(summary, slow_endpoints, dependencies)

        return {
            "summary": summary,
            "traffic": {
                "requests_per_second": summary["requests_per_second"],
                "active_requests": summary["active_requests"],
                "total_requests": summary["total_requests"],
                "peak_rps": summary["peak_rps"],
            },
            "status_codes": status_codes,
            "latency": {
                "avg_latency": summary["avg_latency"],
                "min_latency": summary["min_latency"],
                "max_latency": summary["max_latency"],
                "p95_latency": summary["p95_latency"],
                "p99_latency": summary["p99_latency"],
            },
            "workers": workers_data,
            "endpoints": endpoints,
            "slow_endpoints": slow_endpoints,
            "exceptions": exceptions,
            "dependencies": dependencies,
            "background_tasks": background_tasks,
            "uploads": uploads,
            "authentication": authentication,
            "alerts": alerts,
            "health_score": health_score,
        }

    def _compute_health_score(
        self,
        summary: Dict[str, Any],
        slow_endpoints: List[Dict[str, Any]],
        dependencies: List[Dict[str, Any]],
    ) -> tuple[int, List[Dict[str, Any]]]:
        score = 100
        alerts: List[Dict[str, Any]] = []

        total = summary["total_requests"]
        failures = summary["failure_count"]
        avg_lat = summary["avg_latency"]

        if total > 0:
            fail_rate = failures / total
            if fail_rate > 0.05:
                deduction = min(40, int(fail_rate * 100))
                score -= deduction
                alerts.append({
                    "type": "high_failure_rate",
                    "message": f"API failure rate is high: {round(fail_rate * 100, 2)}%",
                    "severity": "critical" if fail_rate > 0.15 else "warning",
                })

        if avg_lat > 500:
            deduction = 10 if avg_lat <= 1000 else 20
            score -= deduction
            alerts.append({
                "type": "slow_response_time",
                "message": f"Average latency is high: {avg_lat}ms",
                "severity": "warning" if avg_lat <= 1000 else "high",
            })

        for dep in dependencies:
            dep_total = dep["total_calls"]
            dep_fails = dep["failure_count"]
            if dep_total > 0:
                dep_fail_rate = dep_fails / dep_total
                if dep_fail_rate > 0.1:
                    score -= 5
                    alerts.append({
                        "type": "dependency_unstable",
                        "message": f"External dependency {dep['name']} is experiencing high failure rate: {round(dep_fail_rate * 100, 2)}%",
                        "severity": "high",
                    })

        crit_slow = sum(1 for s in slow_endpoints if s["severity"] == "Critical")
        high_slow = sum(1 for s in slow_endpoints if s["severity"] == "High")
        if crit_slow > 0 or high_slow > 0:
            deduction = min(20, (crit_slow * 5) + (high_slow * 2))
            score -= deduction
            alerts.append({
                "type": "slow_endpoints_detected",
                "message": f"Detected {crit_slow} critical and {high_slow} high latency endpoints.",
                "severity": "high" if crit_slow > 0 else "warning",
            })

        score = max(0, min(100, score))
        return score, alerts


# Module-level singleton — used by ApiProvider
api_observability_reader = ApiObservabilityReader()
