import subprocess
import time
import os
from datetime import datetime
from app.collector import BaseCollector
from app.evidence import CollectorResult

class RedisCollector(BaseCollector):
    def collect(self, config: dict) -> CollectorResult:
        started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        start_time = time.perf_counter()
        
        timeout = config.get("timeout", 5)
        binary_path = config.get("binary_path")
        host = config.get("host")
        port = config.get("port")
        username = config.get("username", "")
        password = config.get("password", "")
        log_path = config.get("log_path")
        log_lines = config.get("log_lines", 50)
        
        data = {}
        error_msg = None
        success = True
        
        # Build authentication arguments if credentials are provided
        auth_args = []
        if username:
            auth_args.extend(["--user", username])
        if password:
            auth_args.extend(["-a", password])
            
        try:
            # 1. Process Inspection
            p_ps = subprocess.run(["ps", "-ax", "-o", "pid,command"], capture_output=True, text=True, timeout=timeout)
            
            redis_processes = []
            if p_ps.returncode == 0:
                for line in p_ps.stdout.splitlines()[1:]:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    parts = stripped.split(None, 1)
                    if len(parts) < 2:
                        continue
                    pid_str, cmd = parts
                    if "redis-server" in cmd.lower() and "grep" not in cmd.lower():
                        redis_processes.append({
                            "pid": int(pid_str),
                            "command": cmd
                        })
            
            data["running"] = len(redis_processes) > 0
            data["processes"] = redis_processes
            
            # 2. Redis Connection / Ping Check
            ping_cmd = [binary_path, "-h", host, "-p", str(port)] + auth_args + ["ping"]
            p_ping = subprocess.run(ping_cmd, capture_output=True, text=True, timeout=timeout)
            
            data["ping_check"] = {
                "exit_code": p_ping.returncode,
                "stdout": p_ping.stdout.strip(),
                "stderr": p_ping.stderr.strip()
            }
            
            # 3. Redis Info / Diagnostics Check
            diagnostics = {}
            raw_info_warning = None
            
            try:
                info_cmd = [binary_path, "-h", host, "-p", str(port)] + auth_args + ["info"]
                p_info = subprocess.run(info_cmd, capture_output=True, text=True, timeout=timeout)
                if p_info.returncode == 0:
                    info_map = {}
                    for line in p_info.stdout.splitlines():
                        line_stripped = line.strip()
                        if not line_stripped or line_stripped.startswith("#"):
                            continue
                        if ":" in line_stripped:
                            k, v = line_stripped.split(":", 1)
                            info_map[k.strip()] = v.strip()
                            
                    diagnostics["redis_version"] = info_map.get("redis_version")
                    diagnostics["connected_clients"] = int(info_map["connected_clients"]) if info_map.get("connected_clients", "").isdigit() else None
                    diagnostics["used_memory_human"] = info_map.get("used_memory_human")
                    diagnostics["uptime_in_seconds"] = int(info_map["uptime_in_seconds"]) if info_map.get("uptime_in_seconds", "").isdigit() else None
                    diagnostics["role"] = info_map.get("role")
                    diagnostics["raw_info_warning"] = None
                else:
                    raw_info_warning = f"redis-cli info returned exit code {p_info.returncode}: {p_info.stderr.strip()}"
            except Exception as info_err:
                raw_info_warning = str(info_err)
                
            if raw_info_warning:
                diagnostics["redis_version"] = None
                diagnostics["connected_clients"] = None
                diagnostics["used_memory_human"] = None
                diagnostics["uptime_in_seconds"] = None
                diagnostics["role"] = None
                diagnostics["raw_info_warning"] = raw_info_warning
                
            data["diagnostics"] = diagnostics
            
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
