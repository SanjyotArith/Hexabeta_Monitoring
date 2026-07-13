import subprocess
import time
import os
import yaml
from datetime import datetime
from app.collector import BaseCollector
from app.evidence import CollectorResult

class CloudflaredCollector(BaseCollector):
    def collect(self, config: dict) -> CollectorResult:
        started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        start_time = time.perf_counter()
        
        tunnel_name = config.get("tunnel_name")
        config_path = config.get("config_path")
        log_path = config.get("log_path")
        log_lines = config.get("log_lines", 50)
        
        data = {}
        error_msg = None
        success = True
        
        try:
            # 1. Process Identification (Verify config_path is in command line to match ONLY production instance)
            p_ps = subprocess.run(["ps", "-ax", "-o", "pid,command"], capture_output=True, text=True, timeout=5)
            
            prod_processes = []
            if p_ps.returncode == 0:
                for line in p_ps.stdout.splitlines()[1:]:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    parts = stripped.split(None, 1)
                    if len(parts) < 2:
                        continue
                    pid_str, cmd = parts
                    
                    # Target only the production instance using configuration path
                    if "cloudflared" in cmd.lower() and config_path in cmd:
                        prod_processes.append({
                            "pid": int(pid_str),
                            "command": cmd
                        })
            
            data["running"] = len(prod_processes) > 0
            data["processes"] = prod_processes
            data["tunnel_name"] = tunnel_name
            
            # 2. Tunnel & Connector Information
            p_info = subprocess.run(["cloudflared", "tunnel", "info", tunnel_name], capture_output=True, text=True, timeout=5)
            data["tunnel_info"] = {
                "exit_code": p_info.returncode,
                "stdout": p_info.stdout.strip(),
                "stderr": p_info.stderr.strip()
            }
            
            # 3. Configuration
            data["config"] = self._read_config_file(config_path)
            
            # 4. Read logs (efficient reading)
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
        
    def _read_config_file(self, filepath: str) -> dict:
        if not os.path.exists(filepath):
            return {"error": f"File not found: {filepath}"}
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = yaml.safe_load(f)
                return content if isinstance(content, dict) else {"content": str(content)}
        except Exception as e:
            return {"error": f"Error reading config: {str(e)}"}
            
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
