"""
HexaAgent — API Observability Engine (Phase 3).

High-performance, worker-safe, thread-safe API monitoring subsystem.
Tracks requests, latency percentiles, worker processes, dependencies,
uploads, background tasks, and authentication events using a WAL-mode SQLite buffer.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sqlite3
import time
import httpx
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional, Dict, List
import psutil

logger = logging.getLogger("hexa_agent.api_observability")

# --- Route template normalizer helper ---
def get_route_template(request: Any) -> str:
    route = request.scope.get("route")
    if route and hasattr(route, "path"):
        return route.path
    path = request.url.path
    # Replace numeric segments (e.g. /123/ or at end) with {id}
    path = re.sub(r'/\d+(?=/|$)', '/{id}', path)
    # Replace UUID-like segments with {id}
    path = re.sub(r'/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}(?=/|$)', '/{id}', path)
    return path


class ApiObservabilityEngine:
    def __init__(self) -> None:
        self.db_dir = Path(__file__).resolve().parent.parent.parent / "data"
        self.db_path = self.db_dir / "api_observability.db"
        self._write_queue: asyncio.Queue = asyncio.Queue()
        self._flush_task: Optional[asyncio.Task] = None
        self.active_requests: int = 0
        self.handled_requests: int = 0
        self._peak_rps: float = 0.0
        self._init_db()

    def _init_db(self) -> None:
        try:
            self.db_dir.mkdir(exist_ok=True)
            with sqlite3.connect(self.db_path, timeout=10) as conn:
                conn.execute("PRAGMA journal_mode=WAL;")
                conn.execute("PRAGMA synchronous=NORMAL;")
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS requests (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        method TEXT NOT NULL,
                        route TEXT NOT NULL,
                        status_code INTEGER NOT NULL,
                        processing_time REAL NOT NULL,
                        response_size INTEGER NOT NULL,
                        client_ip TEXT NOT NULL,
                        user_agent TEXT NOT NULL,
                        user_id TEXT,
                        worker_pid INTEGER NOT NULL,
                        exception_type TEXT
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS dependency_calls (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        name TEXT NOT NULL,
                        latency_ms REAL NOT NULL,
                        success INTEGER NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS auth_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        event_type TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS background_tasks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        task_name TEXT NOT NULL,
                        status TEXT NOT NULL,
                        execution_time REAL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS upload_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        upload_type TEXT NOT NULL,
                        size_bytes INTEGER NOT NULL,
                        latency_ms REAL NOT NULL,
                        success INTEGER NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS worker_stats (
                        pid INTEGER PRIMARY KEY,
                        last_seen TEXT NOT NULL,
                        handled_requests INTEGER DEFAULT 0,
                        active_requests INTEGER DEFAULT 0
                    )
                    """
                )
                conn.commit()
        except Exception as e:
            logger.exception("Failed to initialize api observability database: %s", e)

    def start(self) -> None:
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.create_task(self._flush_loop())

    async def stop(self) -> None:
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass

    async def _flush_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(1.0)
                items = []
                while not self._write_queue.empty() and len(items) < 100:
                    try:
                        items.append(self._write_queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break
                
                if items:
                    await asyncio.to_thread(self._batch_write, items)
            except asyncio.CancelledError:
                items = []
                while not self._write_queue.empty():
                    items.append(self._write_queue.get_nowait())
                if items:
                    self._batch_write(items)
                break
            except Exception as e:
                logger.exception("Error in observability flush loop: %s", e)

    def _batch_write(self, items: List[Dict[str, Any]]) -> None:
        try:
            with sqlite3.connect(self.db_path, timeout=15) as conn:
                conn.execute("BEGIN TRANSACTION;")
                for item in items:
                    t = item["type"]
                    d = item["data"]
                    if t == "request":
                        conn.execute(
                            """
                            INSERT INTO requests (
                                timestamp, method, route, status_code, processing_time,
                                response_size, client_ip, user_agent, user_id, worker_pid, exception_type
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                d["timestamp"], d["method"], d["route"], d["status_code"], d["processing_time"],
                                d["response_size"], d["client_ip"], d["user_agent"], d["user_id"], d["worker_pid"], d["exception_type"]
                            )
                        )
                    elif t == "dependency":
                        conn.execute(
                            "INSERT INTO dependency_calls (timestamp, name, latency_ms, success) VALUES (?, ?, ?, ?)",
                            (d["timestamp"], d["name"], d["latency_ms"], d["success"])
                        )
                    elif t == "auth":
                        conn.execute(
                            "INSERT INTO auth_events (timestamp, event_type) VALUES (?, ?)",
                            (d["timestamp"], d["event_type"])
                        )
                    elif t == "background_task":
                        conn.execute(
                            "INSERT INTO background_tasks (timestamp, task_name, status, execution_time) VALUES (?, ?, ?, ?)",
                            (d["timestamp"], d["task_name"], d["status"], d["execution_time"])
                        )
                    elif t == "upload":
                        conn.execute(
                            "INSERT INTO upload_events (timestamp, upload_type, size_bytes, latency_ms, success) VALUES (?, ?, ?, ?, ?)",
                            (d["timestamp"], d["upload_type"], d["size_bytes"], d["latency_ms"], d["success"])
                        )
                    elif t == "worker":
                        conn.execute(
                            "INSERT OR REPLACE INTO worker_stats (pid, last_seen, handled_requests, active_requests) VALUES (?, ?, ?, ?)",
                            (d["pid"], d["last_seen"], d["handled_requests"], d["active_requests"])
                        )
                conn.commit()

                # Prune records older than 24 hours
                cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
                cutoff_str = cutoff.isoformat()
                conn.execute("DELETE FROM requests WHERE timestamp < ?", (cutoff_str,))
                conn.execute("DELETE FROM dependency_calls WHERE timestamp < ?", (cutoff_str,))
                conn.execute("DELETE FROM auth_events WHERE timestamp < ?", (cutoff_str,))
                conn.execute("DELETE FROM background_tasks WHERE timestamp < ?", (cutoff_str,))
                conn.execute("DELETE FROM upload_events WHERE timestamp < ?", (cutoff_str,))
                worker_cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
                conn.execute("DELETE FROM worker_stats WHERE last_seen < ?", (worker_cutoff.isoformat(),))
                conn.commit()
        except Exception as e:
            logger.error("Failed to perform batch write to observability DB: %s", e)

    def record_request(self, **kwargs) -> None:
        self.handled_requests += 1
        self._write_queue.put_nowait({"type": "request", "data": kwargs})
        # Periodically update worker stats
        self._write_queue.put_nowait({
            "type": "worker",
            "data": {
                "pid": os.getpid(),
                "last_seen": datetime.now(timezone.utc).isoformat(),
                "handled_requests": self.handled_requests,
                "active_requests": max(0, self.active_requests)
            }
        })

    def record_dependency_call(self, name: str, latency_ms: float, success: bool) -> None:
        self._write_queue.put_nowait({
            "type": "dependency",
            "data": {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "name": name,
                "latency_ms": latency_ms,
                "success": 1 if success else 0
            }
        })

    def record_auth_event(self, event_type: str) -> None:
        self._write_queue.put_nowait({
            "type": "auth",
            "data": {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event_type": event_type
            }
        })

    def record_background_task(self, task_name: str, status: str, execution_time: Optional[float] = None) -> None:
        self._write_queue.put_nowait({
            "type": "background_task",
            "data": {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "task_name": task_name,
                "status": status,
                "execution_time": execution_time
            }
        })

    def record_upload(self, upload_type: str, size_bytes: int, latency_ms: float, success: bool) -> None:
        self._write_queue.put_nowait({
            "type": "upload",
            "data": {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "upload_type": upload_type,
                "size_bytes": size_bytes,
                "latency_ms": latency_ms,
                "success": 1 if success else 0
            }
        })

    def get_metrics(self) -> dict[str, Any]:
        """Aggregate metrics from SQLite database."""
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
        endpoints = []
        slow_endpoints = []
        exceptions = []
        dependencies = []
        background_tasks = []
        uploads = {
            "image_uploads_count": 0,
            "document_uploads_count": 0,
            "avg_upload_time_ms": 0.0,
            "largest_upload_bytes": 0,
            "failed_uploads_count": 0
        }
        authentication = {
            "successful_logins": 0,
            "failed_logins": 0,
            "expired_tokens": 0,
            "invalid_tokens": 0
        }
        
        try:
            with sqlite3.connect(self.db_path, timeout=5) as conn:
                conn.row_factory = sqlite3.Row
                
                # 1. Total & Success/Failure Counts
                cursor = conn.execute(
                    """
                    SELECT 
                        count(*) as total,
                        sum(case when status_code >= 200 and status_code < 400 then 1 else 0 end) as success,
                        sum(case when status_code >= 400 or exception_type is not null then 1 else 0 end) as failure,
                        avg(processing_time) as avg_lat,
                        min(processing_time) as min_lat,
                        max(processing_time) as max_lat
                    FROM requests
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

                # 2. Latency Percentiles (P95, P99)
                cursor = conn.execute("SELECT processing_time FROM requests ORDER BY processing_time ASC")
                latencies = [r["processing_time"] for r in cursor.fetchall()]
                if latencies:
                    n = len(latencies)
                    summary["p95_latency"] = round(latencies[int(n * 0.95)], 2)
                    summary["p99_latency"] = round(latencies[int(n * 0.99)], 2)

                # 3. Status Codes Distribution
                cursor = conn.execute("SELECT status_code, count(*) as cnt FROM requests GROUP BY status_code")
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

                # 4. Requests Per Second (RPS) in last 10s
                cursor = conn.execute("SELECT count(*) as cnt FROM requests WHERE timestamp >= ?", (ten_sec_ago,))
                ten_sec_count = cursor.fetchone()["cnt"]
                current_rps = round(ten_sec_count / 10.0, 2)
                summary["requests_per_second"] = current_rps
                
                # Update Peak RPS
                if current_rps > self._peak_rps:
                    self._peak_rps = current_rps
                summary["peak_rps"] = self._peak_rps

                # 5. Active Requests (sum across workers)
                cursor = conn.execute("SELECT sum(active_requests) as active FROM worker_stats")
                summary["active_requests"] = cursor.fetchone()["active"] or 0

                # 6. Endpoint Statistics
                cursor = conn.execute(
                    """
                    SELECT route, method, count(*) as total,
                           sum(case when status_code >= 200 and status_code < 400 then 1 else 0 end) as success,
                           sum(case when status_code >= 400 or exception_type is not null then 1 else 0 end) as failure,
                           avg(processing_time) as avg_lat,
                           min(processing_time) as min_lat,
                           max(processing_time) as max_lat
                    FROM requests
                    GROUP BY route, method
                    """
                )
                for r in cursor.fetchall():
                    endpoints.append({
                        "route": r["route"],
                        "method": r["method"],
                        "total_requests": r["total"],
                        "success_count": r["success"] or 0,
                        "failure_count": r["failure"] or 0,
                        "avg_latency": round(r["avg_lat"] or 0.0, 2),
                        "min_latency": round(r["min_lat"] or 0.0, 2),
                        "max_latency": round(r["max_lat"] or 0.0, 2)
                    })

                # 7. Slow APIs Detection (latency >= 500ms)
                cursor = conn.execute(
                    """
                    SELECT route, method, processing_time, timestamp, status_code 
                    FROM requests 
                    WHERE processing_time >= 500 
                    ORDER BY processing_time DESC 
                    LIMIT 10
                    """
                )
                for r in cursor.fetchall():
                    lat = r["processing_time"]
                    if lat >= 3000:
                        sev = "Critical"
                    elif lat >= 1000:
                        sev = "High"
                    else:
                        sev = "Warning"
                    slow_endpoints.append({
                        "route": r["route"],
                        "method": r["method"],
                        "latency": round(lat, 2),
                        "timestamp": r["timestamp"],
                        "status_code": r["status_code"],
                        "severity": sev
                    })

                # 8. Exception Analytics
                cursor = conn.execute(
                    """
                    SELECT exception_type, route, method, count(*) as cnt, max(timestamp) as latest
                    FROM requests
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
                        "latest_occurrence": r["latest"]
                    })

                # 9. Dependency Monitoring
                cursor = conn.execute(
                    """
                    SELECT name, count(*) as total,
                           sum(success) as success_cnt,
                           sum(1 - success) as failure_cnt,
                           avg(latency_ms) as avg_lat,
                           min(latency_ms) as min_lat,
                           max(latency_ms) as max_lat
                    FROM dependency_calls
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
                        "max_latency": round(r["max_lat"] or 0.0, 2)
                    })

                # 10. Background Task Monitoring
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
                        "avg_execution_time": round(r["avg_exec"] or 0.0, 2) if r["avg_exec"] else 0.0
                    })

                # 11. Upload Monitoring
                cursor = conn.execute(
                    """
                    SELECT upload_type, count(*) as total,
                           sum(case when success = 0 then 1 else 0 end) as failed,
                           avg(latency_ms) as avg_lat,
                           max(size_bytes) as max_size
                    FROM upload_events
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

                # 12. Authentication Analytics
                cursor = conn.execute("SELECT event_type, count(*) as cnt FROM auth_events GROUP BY event_type")
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
            logger.error("Error retrieving api observability metrics: %s", e)

        # 13. Worker Details (psutil runtime mapping)
        workers_info = self.get_uvicorn_workers()
        # Retrieve worker stats from database (handled requests, active requests)
        worker_details = []
        db_pids = set()
        try:
            with sqlite3.connect(self.db_path, timeout=5) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("SELECT pid, handled_requests, active_requests FROM worker_stats")
                for r in cursor.fetchall():
                    db_pids.add(r["pid"])
                    # Find matching psutil worker
                    matching = next((w for w in workers_info if w["pid"] == r["pid"]), None)
                    worker_details.append({
                        "pid": r["pid"],
                        "cpu_percent": matching["cpu_percent"] if matching else 0.0,
                        "memory_mb": matching["memory_mb"] if matching else 0.0,
                        "handled_requests": r["handled_requests"],
                        "active_requests": r["active_requests"]
                    })
        except Exception:
            pass

        # Calculate restart count (PIDs in DB but not currently active processes)
        active_pids = {w["pid"] for w in workers_info}
        restart_count = max(0, len(db_pids - active_pids))

        workers_data = {
            "active_workers_count": len(workers_info),
            "restart_count": restart_count,
            "worker_details": worker_details
        }

        # 14. Compute Health Score & Alerts
        health_score, alerts = self.compute_health_score(summary, slow_endpoints, dependencies)

        return {
            "summary": summary,
            "traffic": {
                "requests_per_second": summary["requests_per_second"],
                "active_requests": summary["active_requests"],
                "total_requests": summary["total_requests"],
                "peak_rps": summary["peak_rps"]
            },
            "status_codes": status_codes,
            "latency": {
                "avg_latency": summary["avg_latency"],
                "min_latency": summary["min_latency"],
                "max_latency": summary["max_latency"],
                "p95_latency": summary["p95_latency"],
                "p99_latency": summary["p99_latency"]
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
            "health_score": health_score
        }

    def get_uvicorn_workers(self) -> List[Dict[str, Any]]:
        workers = []
        try:
            current_proc = psutil.Process(os.getpid())
            parent_proc = current_proc.parent()
            
            if parent_proc:
                children = parent_proc.children(recursive=False)
                for child in children:
                    try:
                        cpu = child.cpu_percent(interval=None)
                        mem_mb = round(child.memory_info().rss / (1024 * 1024), 2)
                        workers.append({
                            "pid": child.pid,
                            "cpu_percent": cpu,
                            "memory_mb": mem_mb
                        })
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
            
            if not workers:
                cpu = current_proc.cpu_percent(interval=None)
                mem_mb = round(current_proc.memory_info().rss / (1024 * 1024), 2)
                workers.append({
                    "pid": current_proc.pid,
                    "cpu_percent": cpu,
                    "memory_mb": mem_mb
                })
        except Exception as e:
            logger.error("Failed to gather uvicorn worker processes: %s", e)
        return workers

    def compute_health_score(self, summary: Dict[str, Any], slow_endpoints: List[Dict[str, Any]], dependencies: List[Dict[str, Any]]) -> tuple[int, List[Dict[str, Any]]]:
        score = 100
        alerts = []

        total = summary["total_requests"]
        failures = summary["failure_count"]
        avg_lat = summary["avg_latency"]

        # Failure rate deduction (max 40 points)
        if total > 0:
            fail_rate = failures / total
            if fail_rate > 0.05:
                deduction = min(40, int(fail_rate * 100))
                score -= deduction
                alerts.append({
                    "type": "high_failure_rate",
                    "message": f"API failure rate is high: {round(fail_rate * 100, 2)}%",
                    "severity": "critical" if fail_rate > 0.15 else "warning"
                })

        # Latency deduction (max 20 points)
        if avg_lat > 500:
            deduction = 10 if avg_lat <= 1000 else 20
            score -= deduction
            alerts.append({
                "type": "slow_response_time",
                "message": f"Average latency is high: {avg_lat}ms",
                "severity": "warning" if avg_lat <= 1000 else "high"
            })

        # Dependency failures deduction (max 20 points)
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
                        "severity": "high"
                    })

        # Slow APIs deduction (max 20 points)
        crit_slow = sum(1 for s in slow_endpoints if s["severity"] == "Critical")
        high_slow = sum(1 for s in slow_endpoints if s["severity"] == "High")
        if crit_slow > 0 or high_slow > 0:
            deduction = min(20, (crit_slow * 5) + (high_slow * 2))
            score -= deduction
            alerts.append({
                "type": "slow_endpoints_detected",
                "message": f"Detected {crit_slow} critical and {high_slow} high latency endpoints.",
                "severity": "high" if crit_slow > 0 else "warning"
            })

        score = max(0, min(100, score))
        return score, alerts


# Single global engine instance
api_observability_engine = ApiObservabilityEngine()


# --- Monkey Patching Logic ---
def patch_all_dependencies() -> None:
    """Monkey patches standard client libraries to track dependency latency/success."""
    logger.info("Patching external dependency clients for observability...")

    # 1. Patch HTTPX Async & Sync Clients
    try:
        original_async_send = httpx.AsyncClient.send
        async def patched_async_send(self, request, *args, **kwargs):
            url_str = str(request.url)
            from app.core.config import get_settings
            settings = get_settings()
            # Prevent tracing own healthchecks and monitor pushes
            is_internal = "localhost" in url_str or "127.0.0.1" in url_str or settings.MONITOR_URL in url_str
            
            if is_internal:
                return await original_async_send(self, request, *args, **kwargs)
                
            dep_name = "External HTTP APIs"
            if "11434" in url_str or "/api/generate" in url_str or "/api/chat" in url_str:
                dep_name = "Ollama"
                
            start = time.monotonic()
            success = False
            try:
                response = await original_async_send(self, request, *args, **kwargs)
                success = 200 <= response.status_code < 400
                return response
            finally:
                elapsed = (time.monotonic() - start) * 1000
                api_observability_engine.record_dependency_call(dep_name, elapsed, success)

        httpx.AsyncClient.send = patched_async_send

        original_sync_send = httpx.Client.send
        def patched_sync_send(self, request, *args, **kwargs):
            url_str = str(request.url)
            from app.core.config import get_settings
            settings = get_settings()
            is_internal = "localhost" in url_str or "127.0.0.1" in url_str or settings.MONITOR_URL in url_str
            
            if is_internal:
                return original_sync_send(self, request, *args, **kwargs)
                
            dep_name = "External HTTP APIs"
            if "11434" in url_str or "/api/generate" in url_str or "/api/chat" in url_str:
                dep_name = "Ollama"
                
            start = time.monotonic()
            success = False
            try:
                response = original_sync_send(self, request, *args, **kwargs)
                success = 200 <= response.status_code < 400
                return response
            finally:
                elapsed = (time.monotonic() - start) * 1000
                api_observability_engine.record_dependency_call(dep_name, elapsed, success)

        httpx.Client.send = patched_sync_send
        logger.info("HTTPX clients patched successfully.")
    except Exception as e:
        logger.error("Failed to patch HTTPX: %s", e)

    # 2. Patch PostgreSQL (asyncpg)
    try:
        import asyncpg
        for method_name in ("execute", "fetch", "fetchval", "fetchrow"):
            if hasattr(asyncpg.Connection, method_name):
                orig = getattr(asyncpg.Connection, method_name)
                def make_patched_postgres(original_method):
                    async def patched(self, *args, **kwargs):
                        start = time.monotonic()
                        success = False
                        try:
                            res = await original_method(self, *args, **kwargs)
                            success = True
                            return res
                        finally:
                            elapsed = (time.monotonic() - start) * 1000
                            api_observability_engine.record_dependency_call("PostgreSQL", elapsed, success)
                    return patched
                setattr(asyncpg.Connection, method_name, make_patched_postgres(orig))
        logger.info("asyncpg Connection patched successfully.")
    except ImportError:
        pass
    except Exception as e:
        logger.error("Failed to patch asyncpg: %s", e)

    # 3. Patch Redis (redis and redis.asyncio)
    try:
        import redis
        if hasattr(redis, "Redis"):
            orig_execute = redis.Redis.execute_command
            def patched_redis_execute(self, *args, **kwargs):
                start = time.monotonic()
                success = False
                try:
                    res = orig_execute(self, *args, **kwargs)
                    success = True
                    return res
                finally:
                    elapsed = (time.monotonic() - start) * 1000
                    api_observability_engine.record_dependency_call("Redis", elapsed, success)
            redis.Redis.execute_command = patched_redis_execute

        import redis.asyncio as aioredis
        if hasattr(aioredis, "Redis"):
            orig_async_execute = aioredis.Redis.execute_command
            async def patched_redis_async_execute(self, *args, **kwargs):
                start = time.monotonic()
                success = False
                try:
                    res = await orig_async_execute(self, *args, **kwargs)
                    success = True
                    return res
                finally:
                    elapsed = (time.monotonic() - start) * 1000
                    api_observability_engine.record_dependency_call("Redis", elapsed, success)
            aioredis.Redis.execute_command = patched_redis_async_execute
        logger.info("redis-py clients patched successfully.")
    except ImportError:
        pass
    except Exception as e:
        logger.error("Failed to patch Redis: %s", e)

    # 4. Patch MongoDB (pymongo)
    try:
        import pymongo
        orig_command = pymongo.collection.Collection._command
        def patched_mongo_command(self, *args, **kwargs):
            start = time.monotonic()
            success = False
            try:
                res = orig_command(self, *args, **kwargs)
                success = True
                return res
            finally:
                elapsed = (time.monotonic() - start) * 1000
                api_observability_engine.record_dependency_call("MongoDB", elapsed, success)
        pymongo.collection.Collection._command = patched_mongo_command
        logger.info("pymongo Collection patched successfully.")
    except ImportError:
        pass
    except Exception as e:
        logger.error("Failed to patch pymongo: %s", e)

    # 5. Patch SMTP (smtplib)
    try:
        import smtplib
        for smtp_cls in (smtplib.SMTP, smtplib.SMTP_SSL):
            if hasattr(smtp_cls, "sendmail"):
                orig_send = smtp_cls.sendmail
                def make_patched_smtp(original):
                    def patched(self, *args, **kwargs):
                        start = time.monotonic()
                        success = False
                        try:
                            res = original(self, *args, **kwargs)
                            success = True
                            return res
                        finally:
                            elapsed = (time.monotonic() - start) * 1000
                            api_observability_engine.record_dependency_call("SMTP", elapsed, success)
                    return patched
                smtp_cls.sendmail = make_patched_smtp(orig_send)
        logger.info("smtplib SMTP clients patched successfully.")
    except Exception as e:
        logger.error("Failed to patch smtplib: %s", e)

    # 6. Patch FastAPI BackgroundTasks
    try:
        from starlette.background import BackgroundTasks as StarletteBackgroundTasks
        original_add_task = StarletteBackgroundTasks.add_task
        def patched_add_task(self, func, *args, **kwargs):
            task_name = getattr(func, "__name__", str(func))
            
            async def wrapper(*w_args, **w_kwargs):
                start = time.monotonic()
                api_observability_engine.record_background_task(task_name, "running")
                try:
                    if asyncio.iscoroutinefunction(func):
                        res = await func(*w_args, **w_kwargs)
                    else:
                        res = await asyncio.to_thread(func, *w_args, **w_kwargs)
                    elapsed = (time.monotonic() - start) * 1000
                    api_observability_engine.record_background_task(task_name, "completed", elapsed)
                    return res
                except Exception as ex:
                    elapsed = (time.monotonic() - start) * 1000
                    api_observability_engine.record_background_task(task_name, "failed", elapsed)
                    raise ex
            original_add_task(self, wrapper, *args, **kwargs)
        StarletteBackgroundTasks.add_task = patched_add_task
        logger.info("FastAPI BackgroundTasks patched successfully.")
    except Exception as e:
        logger.error("Failed to patch BackgroundTasks: %s", e)


from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request

class ApiObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        from app.core.api_observability import api_observability_engine, get_route_template
        api_observability_engine.active_requests += 1
        
        start_time = time.monotonic()
        timestamp = datetime.now(timezone.utc).isoformat()
        exception_type = None
        status_code = 500
        response_size = 0
        
        try:
            response = await call_next(request)
            status_code = response.status_code
            if "content-length" in response.headers:
                try:
                    response_size = int(response.headers["content-length"])
                except ValueError:
                    pass
            
            # --- Detect Authentication Analytics ---
            path = request.url.path.lower()
            if "login" in path or "signin" in path or "token" in path:
                if 200 <= status_code < 300:
                    api_observability_engine.record_auth_event("login_success")
                elif status_code in (401, 403):
                    api_observability_engine.record_auth_event("login_failure")
                    
            if status_code == 401:
                auth_header = request.headers.get("authorization", "").lower()
                www_auth = response.headers.get("www-authenticate", "").lower()
                if "expired" in www_auth or "expired" in response.headers.get("x-error", "").lower():
                    api_observability_engine.record_auth_event("token_expired")
                elif "invalid" in www_auth or "invalid" in response.headers.get("x-error", "").lower():
                    api_observability_engine.record_auth_event("token_invalid")
                elif auth_header:
                    api_observability_engine.record_auth_event("token_invalid")
            
            # --- Detect Upload Monitoring ---
            content_type = request.headers.get("content-type", "").lower()
            if "multipart/form-data" in content_type:
                is_image = any(x in path for x in ("image", "png", "jpg", "jpeg", "gif"))
                upload_type = "image" if is_image else "document"
                
                size_bytes = 0
                if "content-length" in request.headers:
                    try:
                        size_bytes = int(request.headers["content-length"])
                    except ValueError:
                        pass
                
                success = (200 <= status_code < 400)
                elapsed = (time.monotonic() - start_time) * 1000
                api_observability_engine.record_upload(upload_type, size_bytes, elapsed, success)

            return response
        except Exception as e:
            exception_type = type(e).__name__
            exc_msg = str(e).lower()
            if "expired" in exc_msg:
                api_observability_engine.record_auth_event("token_expired")
            elif "invalid" in exc_msg or "jwt" in exc_msg:
                api_observability_engine.record_auth_event("token_invalid")
            raise e
        finally:
            api_observability_engine.active_requests = max(0, api_observability_engine.active_requests - 1)
            processing_time = (time.monotonic() - start_time) * 1000
            
            method = request.method
            route = get_route_template(request)
            client_ip = request.client.host if request.client else "unknown"
            user_agent = request.headers.get("user-agent", "unknown")
            
            user_id = None
            for attr in ("user_id", "user"):
                if hasattr(request.state, attr):
                    val = getattr(request.state, attr)
                    if val:
                        if hasattr(val, "id"):
                            user_id = str(val.id)
                        elif hasattr(val, "username"):
                            user_id = str(val.username)
                        else:
                            user_id = str(val)
                        break

            api_observability_engine.record_request(
                timestamp=timestamp,
                method=method,
                route=route,
                status_code=status_code,
                processing_time=processing_time,
                response_size=response_size,
                client_ip=client_ip,
                user_agent=user_agent,
                user_id=user_id,
                worker_pid=os.getpid(),
                exception_type=exception_type
            )
