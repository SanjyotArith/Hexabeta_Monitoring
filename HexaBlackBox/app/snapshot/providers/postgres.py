import os
import re
import sys
import time
import subprocess
import psycopg2
from datetime import datetime, timezone
from typing import List, Optional, Any
from app.snapshot.models import SnapshotContext, SnapshotProvider, CapturedArtifact, ProviderCaptureResult
from app.snapshot.redaction import redact_content

def sanitize_query(query: str, max_query_length: int) -> str:
    """
    Sanitizes SQL query text fields by replacing string literals and numbers with '?'
    to prevent logging sensitive user/application values, then applies standard redactions and truncation.
    """
    if not query:
        return ""
    try:
        # Replace string literals
        query = re.sub(r"'(.*?)'", "'?'", query)
        # Replace numeric literals
        query = re.sub(r"\b\d+\b", "?", query)
        # Apply standard redactions (JWTs, Bearer tokens, cookies, passwords, database credentials)
        query = redact_content(query)
        # Truncate to maximum length
        if len(query) > max_query_length:
            query = query[:max_query_length] + "... [TRUNCATED]"
        return query
    except Exception as e:
        return f"[Sanitization Failed: {e}]"


class PostgreSQLSnapshotProvider(SnapshotProvider):
    @property
    def name(self) -> str:
        return "postgres"


class MacOSPostgreSQLSnapshotProvider(PostgreSQLSnapshotProvider):
    def capture(self, context: SnapshotContext) -> ProviderCaptureResult:
        started_at = datetime.now(timezone.utc)
        start_time = time.perf_counter()
        
        provider_config = context.config.get("snapshot", {}).get("providers", {}).get("postgres", {})
        collectors_postgres = context.config.get("collectors", {}).get("postgres", {})
        
        # 1. Config Resolution & Precedence Fallback
        host = provider_config.get("host") or collectors_postgres.get("host", "localhost")
        port = provider_config.get("port") or collectors_postgres.get("port", 5432)
        connect_timeout = provider_config.get("connect_timeout") or collectors_postgres.get("timeout", 5)
        query_timeout = provider_config.get("query_timeout") or collectors_postgres.get("timeout", 5)
        max_rows = provider_config.get("max_rows", 50)
        long_running_threshold = provider_config.get("long_running_threshold_seconds", 30)
        max_query_length = provider_config.get("max_query_length", 200)
        
        # Derive statement_timeout in milliseconds dynamically from configured query_timeout
        statement_timeout_ms = int(query_timeout * 1000)
        
        # Target databases to inspect
        databases = provider_config.get("databases") or collectors_postgres.get("databases", [{"name": "postgres", "username": "postgres", "password": ""}])
        
        artifacts: List[CapturedArtifact] = []
        
        # Helper to execute shell commands (e.g. lsof, ps) read-only
        def run_cmd(artifact_name: str, cmd: List[str], method: str) -> CapturedArtifact:
            cmd_start = time.perf_counter()
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, shell=False, timeout=1.0)
                sanitized = redact_content(res.stdout + res.stderr)
                duration = round((time.perf_counter() - cmd_start) * 1000, 2)
                return CapturedArtifact(
                    name=artifact_name,
                    content=sanitized,
                    status="SUCCESS",
                    capture_method=method,
                    captured_at=datetime.now(timezone.utc),
                    duration_ms=duration,
                    exit_code=res.returncode,
                    bytes_captured=len(sanitized.encode("utf-8")),
                    lines_captured=len(sanitized.splitlines())
                )
            except subprocess.TimeoutExpired:
                duration = round((time.perf_counter() - cmd_start) * 1000, 2)
                return CapturedArtifact(
                    name=artifact_name,
                    content="",
                    status="TIMEOUT",
                    capture_method=method,
                    captured_at=datetime.now(timezone.utc),
                    duration_ms=duration,
                    error_message="Command execution timed out"
                )
            except Exception as e:
                duration = round((time.perf_counter() - cmd_start) * 1000, 2)
                return CapturedArtifact(
                    name=artifact_name,
                    content="",
                    status="FAILED",
                    capture_method=method,
                    captured_at=datetime.now(timezone.utc),
                    duration_ms=duration,
                    error_message=str(e)
                )

        # Helper to safely establish a database connection
        def get_db_connection(db_info: dict) -> Any:
            # options argument specifies dynamically derived statement_timeout_ms
            options = f"-c statement_timeout={statement_timeout_ms}"
            return psycopg2.connect(
                host=host,
                port=port,
                dbname=db_info["name"],
                user=db_info["username"],
                password=db_info.get("password", ""),
                connect_timeout=connect_timeout,
                options=options
            )

        # Artifact 1: connectivity.txt (Tests connection status for each configured database target)
        conn_start = time.perf_counter()
        connectivity_lines = []
        connectivity_status = "SUCCESS"
        connections_attempted = 0
        connections_successful = 0
        first_successful_db = None
        
        for db_info in databases:
            connections_attempted += 1
            try:
                # Mask credentials
                masked_user = db_info["username"]
                conn = get_db_connection(db_info)
                conn.close()
                connectivity_lines.append(f"Database: {db_info['name']} | User: {masked_user} | Connection: SUCCESS")
                connections_successful += 1
                if first_successful_db is None:
                    first_successful_db = db_info
            except Exception as e:
                masked_err = redact_content(str(e))
                connectivity_lines.append(f"Database: {db_info['name']} | User: {db_info['username']} | Connection: FAILED | Error: {masked_err}")
                
        # Determine overall connectivity artifact status
        if connections_successful == 0:
            connectivity_status = "FAILED"
        elif connections_successful < connections_attempted:
            connectivity_status = "PARTIAL"
            
        connectivity_content = "\n".join(connectivity_lines)
        conn_duration = round((time.perf_counter() - conn_start) * 1000, 2)
        artifacts.append(CapturedArtifact(
            name="connectivity.txt",
            content=connectivity_content,
            status=connectivity_status,
            capture_method="db-connect-test",
            captured_at=datetime.now(timezone.utc),
            duration_ms=conn_duration,
            bytes_captured=len(connectivity_content.encode("utf-8")),
            lines_captured=len(connectivity_content.splitlines())
        ))

        # Query executing system context (Only runs if at least one database is reachable)
        connections_content = ""
        connections_status = "SUCCESS"
        connections_err = None
        
        activity_content = ""
        activity_status = "SUCCESS"
        activity_err = None
        
        locks_content = ""
        locks_status = "SUCCESS"
        locks_err = None
        
        long_running_content = ""
        long_running_status = "SUCCESS"
        long_running_err = None
        
        if first_successful_db is None:
            # Fallback when all database targets are unreachable
            reason = "Skipped system queries: All configured databases are unreachable"
            connections_content = reason
            connections_status = "FAILED"
            activity_content = reason
            activity_status = "FAILED"
            locks_content = reason
            locks_status = "FAILED"
            long_running_content = reason
            long_running_status = "FAILED"
        else:
            # Artifact 2: connections.txt (utilization calculation)
            conns_start = time.perf_counter()
            try:
                conn = get_db_connection(first_successful_db)
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT 
                            (SELECT setting::int FROM pg_settings WHERE name = 'max_connections') as max_conns,
                            count(*) as total,
                            count(*) filter (where state = 'active') as active,
                            count(*) filter (where state = 'idle') as idle,
                            count(*) filter (where state = 'idle in transaction') as idle_in_txn,
                            count(*) filter (where wait_event IS NOT NULL) as waiting
                        FROM pg_stat_activity;
                    """)
                    row = cur.fetchone()
                    if row:
                        max_conns, total, active, idle, idle_in_txn, waiting = row
                        # Prevent division by zero
                        utilization = round((total / max_conns * 100.0), 2) if max_conns and max_conns > 0 else 0.0
                        connections_content = (
                            f"Max Connections: {max_conns}\n"
                            f"Total Connections: {total}\n"
                            f"Active Sockets: {active}\n"
                            f"Idle Sockets: {idle}\n"
                            f"Idle in Transaction Sockets: {idle_in_txn}\n"
                            f"Waiting Sockets: {waiting}\n"
                            f"Connection Utilization: {utilization}%\n"
                        )
                conn.close()
            except Exception as e:
                connections_status = "FAILED"
                connections_err = str(e)
            
            # Artifact 3: activity.txt (sanitized query statements)
            activity_start_time = time.perf_counter()
            try:
                conn = get_db_connection(first_successful_db)
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT pid, datname, usename, application_name, client_addr, state, wait_event_type, wait_event,
                               round(extract(epoch from (now() - query_start))) as query_age_seconds,
                               query
                        FROM pg_stat_activity
                        WHERE state IS NOT NULL AND pid <> pg_backend_pid()
                        ORDER BY query_age_seconds DESC
                        LIMIT %s;
                    """, (max_rows,))
                    rows = cur.fetchall()
                    lines = ["PID | DB | USER | APP | CLIENT | STATE | WAIT TYPE | WAIT EVENT | AGE(s) | SANITIZED QUERY"]
                    for r in rows:
                        pid, datname, usename, app_name, client_addr, state, wait_type, wait_event, age, raw_query = r
                        san_q = sanitize_query(raw_query, max_query_length)
                        lines.append(f"{pid} | {datname} | {usename} | {app_name} | {client_addr} | {state} | {wait_type} | {wait_event} | {age} | {san_q}")
                    activity_content = "\n".join(lines)
                conn.close()
            except Exception as e:
                activity_status = "FAILED"
                activity_err = str(e)

            # Artifact 4: locks.txt
            locks_start_time = time.perf_counter()
            try:
                conn = get_db_connection(first_successful_db)
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT 
                            blocked_locks.pid     AS blocked_pid,
                            blocked_activity.query    AS blocked_statement,
                            blocking_locks.pid    AS blocking_pid,
                            blocking_activity.query   AS blocking_statement,
                            blocked_locks.mode    AS blocked_mode,
                            blocking_locks.mode   AS blocking_mode
                        FROM pg_catalog.pg_locks         blocked_locks
                        JOIN pg_catalog.pg_stat_activity blocked_activity ON blocked_activity.pid = blocked_locks.pid
                        JOIN pg_catalog.pg_locks         blocking_locks 
                            ON blocking_locks.locktype = blocked_locks.locktype
                            AND blocking_locks.database IS NOT DISTINCT FROM blocked_locks.database
                            AND blocking_locks.relation IS NOT DISTINCT FROM blocked_locks.relation
                            AND blocking_locks.page IS NOT DISTINCT FROM blocked_locks.page
                            AND blocking_locks.tuple IS NOT DISTINCT FROM blocked_locks.tuple
                            AND blocking_locks.virtualxid IS NOT DISTINCT FROM blocked_locks.virtualxid
                            AND blocking_locks.transactionid IS NOT DISTINCT FROM blocked_locks.transactionid
                            AND blocking_locks.classid IS NOT DISTINCT FROM blocked_locks.classid
                            AND blocking_locks.objid IS NOT DISTINCT FROM blocked_locks.objid
                            AND blocking_locks.objsubid IS NOT DISTINCT FROM blocked_locks.objsubid
                            AND blocking_locks.pid <> blocked_locks.pid
                        JOIN pg_catalog.pg_stat_activity blocking_activity ON blocking_activity.pid = blocking_locks.pid
                        WHERE NOT blocked_locks.granted
                        LIMIT %s;
                    """, (max_rows,))
                    rows = cur.fetchall()
                    lines = ["BLOCKED PID | BLOCKED STMT | BLOCKING PID | BLOCKING STMT | BLOCKED MODE | BLOCKING MODE"]
                    for r in rows:
                        b_pid, b_stmt, bl_pid, bl_stmt, b_mode, bl_mode = r
                        b_stmt_san = sanitize_query(b_stmt, max_query_length)
                        bl_stmt_san = sanitize_query(bl_stmt, max_query_length)
                        lines.append(f"{b_pid} | {b_stmt_san} | {bl_pid} | {bl_stmt_san} | {b_mode} | {bl_mode}")
                    locks_content = "\n".join(lines)
                conn.close()
            except Exception as e:
                locks_status = "FAILED"
                locks_err = str(e)

            # Artifact 5: long_running.txt
            long_start_time = time.perf_counter()
            try:
                conn = get_db_connection(first_successful_db)
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT pid, datname, usename, state, 
                               round(extract(epoch from (now() - xact_start))) as txn_age_seconds,
                               query
                        FROM pg_stat_activity
                        WHERE state IS NOT NULL AND xact_start IS NOT NULL AND (now() - xact_start) > interval '%s seconds'
                        ORDER BY txn_age_seconds DESC
                        LIMIT %s;
                    """, (long_running_threshold, max_rows))
                    rows = cur.fetchall()
                    lines = ["PID | DB | USER | STATE | AGE(s) | SANITIZED QUERY"]
                    for r in rows:
                        pid, datname, usename, state, age, raw_query = r
                        san_q = sanitize_query(raw_query, max_query_length)
                        lines.append(f"{pid} | {datname} | {usename} | {state} | {age} | {san_q}")
                    long_running_content = "\n".join(lines)
                conn.close()
            except Exception as e:
                long_running_status = "FAILED"
                long_running_err = str(e)

        # Append execution results for the cluster queries
        artifacts.append(CapturedArtifact(
            name="connections.txt",
            content=connections_content,
            status=connections_status,
            capture_method="db-query",
            captured_at=datetime.now(timezone.utc),
            duration_ms=round((time.perf_counter() - conn_start) * 1000, 2),
            error_message=connections_err,
            bytes_captured=len(connections_content.encode("utf-8")),
            lines_captured=len(connections_content.splitlines())
        ))
        
        artifacts.append(CapturedArtifact(
            name="activity.txt",
            content=activity_content,
            status=activity_status,
            capture_method="db-query",
            captured_at=datetime.now(timezone.utc),
            duration_ms=round((time.perf_counter() - conn_start) * 1000, 2),
            error_message=activity_err,
            bytes_captured=len(activity_content.encode("utf-8")),
            lines_captured=len(activity_content.splitlines())
        ))

        artifacts.append(CapturedArtifact(
            name="locks.txt",
            content=locks_content,
            status=locks_status,
            capture_method="db-query",
            captured_at=datetime.now(timezone.utc),
            duration_ms=round((time.perf_counter() - conn_start) * 1000, 2),
            error_message=locks_err,
            bytes_captured=len(locks_content.encode("utf-8")),
            lines_captured=len(locks_content.splitlines())
        ))

        artifacts.append(CapturedArtifact(
            name="long_running.txt",
            content=long_running_content,
            status=long_running_status,
            capture_method="db-query",
            captured_at=datetime.now(timezone.utc),
            duration_ms=round((time.perf_counter() - conn_start) * 1000, 2),
            error_message=long_running_err,
            bytes_captured=len(long_running_content.encode("utf-8")),
            lines_captured=len(long_running_content.splitlines())
        ))

        # Artifact 6: postgres_processes.txt
        # Standard ps filtering on macOS/Linux for processes matching pg/postgres/postgresql
        expected_process_signature = provider_config.get("process_matching", ["postgres"])
        ps_cmd = ["ps", "-ax", "-o", "pid,ppid,%cpu,%mem,command"]
        ps_art = run_cmd("postgres_processes.txt", ps_cmd, "ps-filter")
        
        # Filter raw ps output in Python to prevent false-positives
        if ps_art.status == "SUCCESS":
            self_pid = os.getpid()
            lines = ps_art.content.splitlines()
            header = lines[0] if lines else "PID PPID %CPU %MEM COMMAND"
            filtered_lines = [header]
            for line in lines[1:]:
                match = any(term in line for term in expected_process_signature)
                if match:
                    parts = line.strip().split()
                    if parts:
                        pid = int(parts[0])
                        if pid != self_pid:
                            filtered_lines.append(line)
            ps_art.content = "\n".join(filtered_lines)
            ps_art.bytes_captured = len(ps_art.content.encode("utf-8"))
            ps_art.lines_captured = len(ps_art.content.splitlines())
            
        artifacts.append(ps_art)

        # Artifact 7: port.txt (Local LISTEN socket check only, matching -sTCP:LISTEN)
        port_start = time.perf_counter()
        try:
            port_cmd = ["lsof", "-n", "-P", "-i", f"tcp:{port}", "-sTCP:LISTEN"]
            res = subprocess.run(port_cmd, capture_output=True, text=True, shell=False, timeout=1.0)
            duration = round((time.perf_counter() - port_start) * 1000, 2)
            
            if res.returncode == 0 and res.stdout.strip():
                port_content = redact_content(res.stdout)
                port_note = "listener-found"
            else:
                port_content = f"Port: {port}\nListening: false\nListener: none\n"
                port_note = "no-listener"
                
            artifacts.append(CapturedArtifact(
                name="port.txt",
                content=port_content,
                status="SUCCESS",
                capture_method=f"lsof-port ({port_note})",
                captured_at=datetime.now(timezone.utc),
                duration_ms=duration,
                exit_code=res.returncode,
                bytes_captured=len(port_content.encode("utf-8")),
                lines_captured=len(port_content.splitlines())
            ))
        except subprocess.TimeoutExpired:
            duration = round((time.perf_counter() - port_start) * 1000, 2)
            artifacts.append(CapturedArtifact(
                name="port.txt",
                content="",
                status="TIMEOUT",
                capture_method="lsof-port",
                captured_at=datetime.now(timezone.utc),
                duration_ms=duration,
                error_message="lsof command timed out"
            ))
        except Exception as e:
            duration = round((time.perf_counter() - port_start) * 1000, 2)
            artifacts.append(CapturedArtifact(
                name="port.txt",
                content="",
                status="FAILED",
                capture_method="lsof-port",
                captured_at=datetime.now(timezone.utc),
                duration_ms=duration,
                error_message=str(e)
            ))

        # Calculate overall status
        success_count = sum(1 for a in artifacts if a.status == "SUCCESS")
        failure_count = sum(1 for a in artifacts if a.status in ("FAILED", "TIMEOUT"))
        
        if success_count == len(artifacts):
            overall_status = "SUCCESS"
        elif failure_count == len(artifacts):
            overall_status = "FAILED"
        else:
            overall_status = "PARTIAL"
            
        finished_at = datetime.now(timezone.utc)
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        
        return ProviderCaptureResult(
            provider_name=self.name,
            status=overall_status,
            artifacts=artifacts,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms
        )


class LinuxPostgreSQLSnapshotProvider(PostgreSQLSnapshotProvider):
    def capture(self, context: SnapshotContext) -> ProviderCaptureResult:
        started_at = datetime.now(timezone.utc)
        return ProviderCaptureResult(
            provider_name=self.name,
            status="FAILED",
            artifacts=[],
            started_at=started_at,
            finished_at=started_at,
            duration_ms=0.0,
            error_message="Linux PostgreSQL provider not implemented in this batch"
        )
