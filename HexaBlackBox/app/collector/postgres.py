import subprocess
import time
import os
from datetime import datetime
from app.collector import BaseCollector
from app.evidence import CollectorResult

class PostgresCollector(BaseCollector):
    def collect(self, config: dict) -> CollectorResult:
        started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        start_time = time.perf_counter()
        
        timeout = config.get("timeout", 5)
        binary_path = config.get("binary_path")
        host = config.get("host")
        port = config.get("port")
        databases = config.get("databases", [])
        log_path = config.get("log_path")
        log_lines = config.get("log_lines", 50)
        
        # Determine credentials of the first database to use for pg_isready checks
        first_db = databases[0] if databases else {}
        username = first_db.get("username", "postgres")
        dbname = first_db.get("name", "postgres")
        
        data = {}
        error_msg = None
        success = True
        
        try:
            # 1. Process Inspection
            p_ps = subprocess.run(["ps", "-ax", "-o", "pid,command"], capture_output=True, text=True, timeout=timeout)
            
            postgres_processes = []
            if p_ps.returncode == 0:
                for line in p_ps.stdout.splitlines()[1:]:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    parts = stripped.split(None, 1)
                    if len(parts) < 2:
                        continue
                    pid_str, cmd = parts
                    # Target postgres and avoid matching python script/grep process
                    if ("postgres" in cmd.lower() or "postmaster" in cmd.lower()) and "grep" not in cmd.lower() and "postgres.py" not in cmd:
                        postgres_processes.append({
                            "pid": int(pid_str),
                            "command": cmd
                        })
            
            data["running"] = len(postgres_processes) > 0
            data["processes"] = postgres_processes
            
            # 2. Connection Check (pg_isready - executed once using first DB credentials)
            cmd_args = [binary_path, "-h", host, "-p", str(port), "-U", username, "-d", dbname]
            p_isready = subprocess.run(cmd_args, capture_output=True, text=True, timeout=timeout)
            
            data["status_check"] = {
                "exit_code": p_isready.returncode,
                "stdout": p_isready.stdout.strip(),
                "stderr": p_isready.stderr.strip()
            }
            
            # 3. Active Connections & Configured Max Connections via psycopg2 (Per Database)
            db_data = {}
            for db_entry in databases:
                db_name = db_entry.get("name")
                db_user = db_entry.get("username")
                db_pass = db_entry.get("password", "")
                
                active_connections = None
                max_connections = None
                db_query_warning = None
                
                try:
                    import psycopg2
                    conn = psycopg2.connect(
                        host=host,
                        port=port,
                        user=db_user,
                        dbname=db_name,
                        password=db_pass,
                        connect_timeout=timeout
                    )
                    try:
                        with conn.cursor() as cur:
                            # Query connections specifically for this database name
                            cur.execute("""
                                SELECT count(*)
                                FROM pg_stat_activity
                                WHERE datname = current_database();
                            """)
                            active_connections = cur.fetchone()[0]
                            
                            # Query max connections configuration limits
                            cur.execute("SELECT setting FROM pg_settings WHERE name = 'max_connections';")
                            max_connections = int(cur.fetchone()[0])
                    finally:
                        conn.close()
                except Exception as db_err:
                    db_query_warning = str(db_err)
                    
                db_data[db_name] = {
                    "active_connections": active_connections,
                    "max_connections": max_connections,
                    "db_query_warning": db_query_warning
                }
                
            data["databases"] = db_data
            
            # 4. Read logs
            data["log"] = self._read_last_lines(log_path, log_lines)
            
        except Exception as e:
            success = False
            error_msg = str(e)
            
        finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        
        return CollectorResult(
            collector_name=self.name,
            success=success,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=round(duration_ms, 2),
            data=data,
            error=error_msg
        )
        
    def _read_last_lines(self, filepath: str, n: int) -> list[str]:
        if not os.path.exists(filepath):
            return [f"File not found: {filepath}"]
        try:
            with open(filepath, "rb") as f:
                f.seek(0, os.SEEK_END)
                file_size = f.tell()
                chunk_size = 4096
                lines = []
                buffer = bytearray()
                pointer = file_size
                
                while pointer > 0 and len(lines) <= n:
                    pointer = max(0, pointer - chunk_size)
                    f.seek(pointer)
                    chunk = f.read(chunk_size if pointer > 0 else file_size)
                    buffer = chunk + buffer
                    lines = buffer.split(b"\n")
                    if pointer == 0:
                        break
                
                if lines and lines[-1] == b"":
                    lines.pop()
                
                result = [line.decode("utf-8", errors="ignore").rstrip() for line in lines[-n:]]
                return result
        except Exception as e:
            return [f"Error reading file: {str(e)}"]
