"""
HexaAgent — API Observability Reader (Phase 3 — Read-Only Consumer).

Reads the API observability database produced by HexaBeta Backend.
HexaAgent is a READ-ONLY consumer; all API observability data is
produced by HexaBeta Backend and stored at:

    Path(settings.HEXABETA_BACKEND_PATH) / "data" / "api_observability.db"

This module aggregates endpoint_registry, request_metrics, failures,
dependency_metrics, uploads, authentication, and worker_statistics
into the snapshot format consumed by HexaMonitor.

Performance Design:
    - ONE query to load endpoint_registry
    - ONE aggregated GROUP BY query over requests for per-endpoint metrics
    - ONE aggregated GROUP BY query over requests for per-endpoint RPS
    - ONE aggregated GROUP BY query over requests for per-endpoint status codes
    - ONE aggregated GROUP BY query over failures for per-endpoint failure info
    - Merge results in memory — NO N+1 query patterns
"""

from __future__ import annotations

import logging
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
    aggregates data for the HexaAgent snapshot endpoint using efficient
    SQL GROUP BY queries. No N+1 patterns.
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
        """
        Aggregate metrics from the backend's SQLite database (read-only).

        Uses efficient GROUP BY SQL queries — no N+1 patterns.
        Scales to 500+, 1000+, 5000+ endpoints.
        """
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
                req_table = self._detect_table(conn, "request_metrics", "requests")

                # ==========================================================
                # STEP 1: Load endpoint_registry (one query)
                # ==========================================================
                cursor = conn.execute("SELECT route, method FROM endpoint_registry")
                registered = set()
                for r in cursor.fetchall():
                    registered.add((r["route"], r["method"]))

                # ==========================================================
                # STEP 2: Aggregated per-endpoint metrics (one GROUP BY query)
                # ==========================================================
                cursor = conn.execute(
                    f"""
                    SELECT
                        route,
                        method,
                        COUNT(*)                                                          AS total_requests,
                        AVG(processing_time)                                              AS avg_latency,
                        MIN(processing_time)                                              AS min_latency,
                        MAX(processing_time)                                              AS max_latency,
                        MAX(timestamp)                                                    AS last_called,
                        SUM(CASE WHEN status_code >= 200 AND status_code < 400 THEN 1 ELSE 0 END) AS success_count,
                        SUM(CASE WHEN status_code >= 400 THEN 1 ELSE 0 END)               AS failure_count
                    FROM {req_table}
                    GROUP BY route, method
                    """
                )
                # Map: (route, method) -> aggregated row dict
                agg_map: Dict[tuple, Dict[str, Any]] = {}
                for r in cursor.fetchall():
                    key = (r["route"], r["method"])
                    agg_map[key] = {
                        "total_requests": r["total_requests"],
                        "avg_latency": round(r["avg_latency"] or 0.0, 2),
                        "min_latency": round(r["min_latency"] or 0.0, 2),
                        "max_latency": round(r["max_latency"] or 0.0, 2),
                        "last_called": r["last_called"],
                        "success_count": r["success_count"] or 0,
                        "failure_count": r["failure_count"] or 0,
                    }

                # ==========================================================
                # STEP 3: Per-endpoint last_status_code (one GROUP BY query)
                # Uses a subquery to get status_code of the latest request.
                # ==========================================================
                cursor = conn.execute(
                    f"""
                    SELECT r.route, r.method, r.status_code AS last_status_code
                    FROM {req_table} r
                    INNER JOIN (
                        SELECT route, method, MAX(timestamp) AS max_ts
                        FROM {req_table}
                        GROUP BY route, method
                    ) latest ON r.route = latest.route
                              AND r.method = latest.method
                              AND r.timestamp = latest.max_ts
                    """
                )
                last_status_map: Dict[tuple, int] = {}
                for r in cursor.fetchall():
                    last_status_map[(r["route"], r["method"])] = r["last_status_code"]

                # ==========================================================
                # STEP 4: Per-endpoint RPS (one GROUP BY query, last 10s)
                # ==========================================================
                cursor = conn.execute(
                    f"""
                    SELECT route, method, COUNT(*) AS recent_count
                    FROM {req_table}
                    WHERE timestamp >= ?
                    GROUP BY route, method
                    """,
                    (ten_sec_ago,),
                )
                rps_map: Dict[tuple, float] = {}
                for r in cursor.fetchall():
                    rps_map[(r["route"], r["method"])] = round(r["recent_count"] / 10.0, 2)

                # ==========================================================
                # STEP 5: Per-endpoint status code distribution (one GROUP BY)
                # ==========================================================
                cursor = conn.execute(
                    f"""
                    SELECT route, method, status_code, COUNT(*) AS cnt
                    FROM {req_table}
                    GROUP BY route, method, status_code
                    """
                )
                sc_map: Dict[tuple, Dict[str, int]] = defaultdict(
                    lambda: {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0}
                )
                for r in cursor.fetchall():
                    key = (r["route"], r["method"])
                    sc = r["status_code"]
                    cnt = r["cnt"]
                    if 200 <= sc < 300:
                        sc_map[key]["2xx"] += cnt
                    elif 300 <= sc < 400:
                        sc_map[key]["3xx"] += cnt
                    elif 400 <= sc < 500:
                        sc_map[key]["4xx"] += cnt
                    elif sc >= 500:
                        sc_map[key]["5xx"] += cnt

                # ==========================================================
                # STEP 6: Per-endpoint p95/p99 — fetch sorted latencies per
                # endpoint in ONE query, compute percentiles in memory
                # ==========================================================
                cursor = conn.execute(
                    f"""
                    SELECT route, method, processing_time
                    FROM {req_table}
                    ORDER BY route, method, processing_time ASC
                    """
                )
                latency_groups: Dict[tuple, List[float]] = defaultdict(list)
                for r in cursor.fetchall():
                    latency_groups[(r["route"], r["method"])].append(r["processing_time"])

                p95_map: Dict[tuple, float] = {}
                p99_map: Dict[tuple, float] = {}
                for key, lats in latency_groups.items():
                    n = len(lats)
                    if n > 0:
                        p95_map[key] = round(lats[min(int(n * 0.95), n - 1)], 2)
                        p99_map[key] = round(lats[min(int(n * 0.99), n - 1)], 2)

                # ==========================================================
                # STEP 7: Active requests per endpoint (one GROUP BY query)
                # ==========================================================
                active_endpoint_map: Dict[tuple, int] = {}
                if self._table_exists(conn, "worker_endpoint_active"):
                    cursor = conn.execute(
                        "SELECT route, method, SUM(active_requests) AS active "
                        "FROM worker_endpoint_active GROUP BY route, method"
                    )
                    for r in cursor.fetchall():
                        active_endpoint_map[(r["route"], r["method"])] = max(0, r["active"])

                # ==========================================================
                # STEP 8: Failures — aggregated per endpoint (one GROUP BY)
                # ==========================================================
                cursor = conn.execute(
                    """
                    SELECT route, method, COUNT(*) AS fail_count,
                           MAX(timestamp) AS last_failure_time
                    FROM failures
                    GROUP BY route, method
                    """
                )
                fail_agg_map: Dict[tuple, Dict[str, Any]] = {}
                for r in cursor.fetchall():
                    fail_agg_map[(r["route"], r["method"])] = {
                        "fail_count": r["fail_count"],
                        "last_failure_time": r["last_failure_time"],
                    }

                # Latest failure details per endpoint (one query with window)
                cursor = conn.execute(
                    """
                    SELECT f.route, f.method, f.timestamp, f.status_code,
                           f.exception_type, f.exception_message,
                           f.failure_reason, f.stack_trace, f.worker_pid
                    FROM failures f
                    INNER JOIN (
                        SELECT route, method, MAX(timestamp) AS max_ts
                        FROM failures
                        GROUP BY route, method
                    ) latest ON f.route = latest.route
                              AND f.method = latest.method
                              AND f.timestamp = latest.max_ts
                    """
                )
                fail_latest_map: Dict[tuple, Dict[str, Any]] = {}
                for r in cursor.fetchall():
                    key = (r["route"], r["method"])
                    fail_latest_map[key] = {
                        "timestamp": r["timestamp"],
                        "status_code": r["status_code"],
                        "exception_type": r["exception_type"],
                        "exception_message": r["exception_message"],
                        "failure_reason": r["failure_reason"],
                        "stack_trace": r["stack_trace"],
                        "worker_pid": r["worker_pid"],
                    }

                # Most common failure reason per endpoint (one GROUP BY)
                cursor = conn.execute(
                    """
                    SELECT route, method, failure_reason, COUNT(*) AS reason_count
                    FROM failures
                    WHERE failure_reason IS NOT NULL
                    GROUP BY route, method, failure_reason
                    ORDER BY route, method, reason_count DESC
                    """
                )
                most_common_failure_map: Dict[tuple, str] = {}
                for r in cursor.fetchall():
                    key = (r["route"], r["method"])
                    # First row per (route, method) is the most common (ORDER BY DESC)
                    if key not in most_common_failure_map:
                        most_common_failure_map[key] = r["failure_reason"]

                # ==========================================================
                # STEP 9: Global summary (one query)
                # ==========================================================
                cursor = conn.execute(
                    f"""
                    SELECT
                        COUNT(*)                                                          AS total,
                        SUM(CASE WHEN status_code >= 200 AND status_code < 400 THEN 1 ELSE 0 END) AS success,
                        SUM(CASE WHEN status_code >= 400 OR exception_type IS NOT NULL THEN 1 ELSE 0 END) AS failure,
                        AVG(processing_time)                                              AS avg_lat,
                        MIN(processing_time)                                              AS min_lat,
                        MAX(processing_time)                                              AS max_lat
                    FROM {req_table}
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

                # Global p95/p99
                cursor = conn.execute(
                    f"SELECT processing_time FROM {req_table} ORDER BY processing_time ASC"
                )
                all_latencies = [r["processing_time"] for r in cursor.fetchall()]
                if all_latencies:
                    n = len(all_latencies)
                    summary["p95_latency"] = round(all_latencies[min(int(n * 0.95), n - 1)], 2)
                    summary["p99_latency"] = round(all_latencies[min(int(n * 0.99), n - 1)], 2)

                # Global status codes (one query)
                cursor = conn.execute(
                    f"SELECT status_code, COUNT(*) AS cnt FROM {req_table} GROUP BY status_code"
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
                    elif sc >= 500:
                        status_codes["5xx"] += cnt

                # Global RPS
                cursor = conn.execute(
                    f"SELECT COUNT(*) AS cnt FROM {req_table} WHERE timestamp >= ?",
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
                        "SELECT SUM(active_requests) AS active FROM worker_stats"
                    )
                    r = cursor.fetchone()
                    summary["active_requests"] = (r["active"] or 0) if r else 0
                else:
                    summary["active_requests"] = sum(active_endpoint_map.values())

                # ==========================================================
                # STEP 10: Merge — build per-endpoint response
                # ==========================================================
                all_endpoint_keys = registered | set(agg_map.keys())

                for route, method in all_endpoint_keys:
                    agg = agg_map.get((route, method))
                    key = (route, method)

                    if agg:
                        total_reqs = agg["total_requests"]
                        success_cnt = agg["success_count"]
                        failure_cnt = agg["failure_count"]
                        avg_l = agg["avg_latency"]
                        min_l = agg["min_latency"]
                        max_l = agg["max_latency"]
                        last_called = agg["last_called"]
                        last_status = last_status_map.get(key)
                    else:
                        # Endpoint registered but no traffic
                        total_reqs = 0
                        success_cnt = 0
                        failure_cnt = 0
                        avg_l = 0.0
                        min_l = 0.0
                        max_l = 0.0
                        last_called = None
                        last_status = None

                    active = active_endpoint_map.get(key, 0)
                    ept_rps = rps_map.get(key, 0.0)
                    p95_l = p95_map.get(key, 0.0)
                    p99_l = p99_map.get(key, 0.0)

                    # Success/failure rates
                    success_rate = 100.0
                    failure_rate = 0.0
                    if total_reqs > 0:
                        success_rate = round((success_cnt / total_reqs) * 100, 2)
                        failure_rate = round((failure_cnt / total_reqs) * 100, 2)

                    # Health Status
                    if total_reqs == 0:
                        health_status = "no_traffic"
                    elif failure_rate > 10.0 or avg_l > 3000:
                        health_status = "critical"
                    elif failure_rate > 2.0 or avg_l > 1000 or p95_l > 2000:
                        health_status = "warning"
                    else:
                        health_status = "healthy"

                    # Failure information from pre-aggregated maps
                    fail_agg = fail_agg_map.get(key)
                    fail_latest = fail_latest_map.get(key)
                    latest_exception = None
                    latest_error_message = None
                    latest_fail_info = None
                    failure_history = None

                    if fail_agg and fail_latest:
                        latest_exception = fail_latest["exception_type"]
                        latest_error_message = fail_latest["exception_message"]

                        latest_fail_info = {
                            "timestamp": fail_latest["timestamp"],
                            "status_code": fail_latest["status_code"],
                            "exception_type": latest_exception,
                            "exception_message": latest_error_message,
                            "failure_reason": fail_latest["failure_reason"],
                            "stack_trace": fail_latest["stack_trace"],
                            "worker_pid": fail_latest["worker_pid"],
                        }

                        failure_history = {
                            "last_failure_time": fail_agg["last_failure_time"],
                            "failure_count": fail_agg["fail_count"],
                            "most_common_failure": most_common_failure_map.get(key),
                            "latest_exception": latest_exception,
                            "latest_error_message": latest_error_message,
                        }

                    # Status code distribution from pre-aggregated map
                    route_sc = sc_map.get(key, {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0})

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
                        "failure_history": failure_history,
                        "status_codes": route_sc,
                    })

                # ==========================================================
                # Slow endpoints (one query, LIMIT 10)
                # ==========================================================
                cursor = conn.execute(
                    f"""
                    SELECT route, method, processing_time, timestamp, status_code
                    FROM {req_table}
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

                # ==========================================================
                # Exception Analytics (one GROUP BY query)
                # ==========================================================
                cursor = conn.execute(
                    f"""
                    SELECT exception_type, route, method,
                           COUNT(*) AS cnt, MAX(timestamp) AS latest
                    FROM {req_table}
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

                # ==========================================================
                # Dependency Monitoring (one GROUP BY query)
                # ==========================================================
                dep_table = self._detect_table(conn, "dependency_metrics", "dependency_calls")
                cursor = conn.execute(
                    f"""
                    SELECT name,
                           COUNT(*)          AS total,
                           SUM(success)      AS success_cnt,
                           SUM(1 - success)  AS failure_cnt,
                           AVG(latency_ms)   AS avg_lat,
                           MIN(latency_ms)   AS min_lat,
                           MAX(latency_ms)   AS max_lat
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

                # ==========================================================
                # Background Task Monitoring (one GROUP BY query)
                # ==========================================================
                if self._table_exists(conn, "background_tasks"):
                    cursor = conn.execute(
                        """
                        SELECT task_name,
                               SUM(CASE WHEN status = 'running'   THEN 1 ELSE 0 END) AS running,
                               SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed,
                               SUM(CASE WHEN status = 'failed'    THEN 1 ELSE 0 END) AS failed,
                               AVG(execution_time)                                    AS avg_exec
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

                # ==========================================================
                # Upload Monitoring (one GROUP BY query)
                # ==========================================================
                upload_table = self._detect_table(conn, "uploads", "upload_events")
                cursor = conn.execute(
                    f"""
                    SELECT upload_type,
                           COUNT(*)                                        AS total,
                           SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END)   AS failed,
                           AVG(latency_ms)                                 AS avg_lat,
                           MAX(size_bytes)                                 AS max_size
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

                # ==========================================================
                # Authentication Analytics (one GROUP BY query)
                # ==========================================================
                auth_table = self._detect_table(conn, "authentication", "auth_events")
                cursor = conn.execute(
                    f"SELECT event_type, COUNT(*) AS cnt FROM {auth_table} GROUP BY event_type"
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

        # ==========================================================
        # Worker Details (psutil + worker_stats — two small queries)
        # ==========================================================
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
                        workers_pid_map = {w["pid"]: w for w in workers_info}
                        for r in cursor.fetchall():
                            db_pids.add(r["pid"])
                            matching = workers_pid_map.get(r["pid"])
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
