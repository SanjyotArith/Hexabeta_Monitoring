import subprocess
import time
import os
from datetime import datetime
from app.collector import BaseCollector
from app.evidence import CollectorResult

class NginxCollector(BaseCollector):
    def collect(self, config: dict) -> CollectorResult:
        started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        start_time = time.perf_counter()
        
        binary_path = config.get("binary_path")
        config_path = config.get("config_path")
        error_log_path = config.get("error_log_path")
        access_log_path = config.get("access_log_path")
        log_lines = config.get("log_lines", 50)
        
        data = {}
        error_msg = None
        success = True
        
        try:
            # 1. Process Inspection
            p_ps = subprocess.run(["ps", "-ax", "-o", "pid,command"], capture_output=True, text=True, timeout=5)
            
            nginx_processes = []
            if p_ps.returncode == 0:
                for line in p_ps.stdout.splitlines()[1:]:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    parts = stripped.split(None, 1)
                    if len(parts) < 2:
                        continue
                    pid_str, cmd = parts
                    if "nginx" in cmd.lower() and "grep" not in cmd.lower():
                        nginx_processes.append({
                            "pid": int(pid_str),
                            "command": cmd
                        })
            
            data["running"] = len(nginx_processes) > 0
            data["processes"] = nginx_processes
            
            # 2. Config validation
            p_config = subprocess.run([binary_path, "-t", "-c", config_path], capture_output=True, text=True, timeout=5)
            data["config_validation"] = {
                "valid": (p_config.returncode == 0),
                "stdout": p_config.stdout.strip(),
                "stderr": p_config.stderr.strip()
            }
            data["config_path"] = config_path
            
            # 3. Read logs
            data["error_log"] = self._read_last_lines(error_log_path, log_lines)
            data["access_log"] = self._read_last_lines(access_log_path, log_lines)
            
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
                
                # If file ends with newline, the split will have an empty trailing string
                if lines and lines[-1] == b"":
                    lines.pop()
                
                result = [line.decode("utf-8", errors="ignore").rstrip() for line in lines[-n:]]
                return result
        except Exception as e:
            return [f"Error reading file: {str(e)}"]
