import subprocess
import time
import re
from datetime import datetime
from app.collector import BaseCollector
from app.evidence import CollectorResult

class SystemCollector(BaseCollector):
    def collect(self, config: dict) -> CollectorResult:
        started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        start_time = time.perf_counter()
        
        timeout = config.get("timeout", 5)
        hostname_command = config.get("hostname_command")
        os_version_command = config.get("os_version_command")
        uptime_command = config.get("uptime_command")
        cpu_command = config.get("cpu_command")
        memory_command = config.get("memory_command")
        disk_command = config.get("disk_command")
        disk_path = config.get("disk_path", "/")
        disk_threshold = config.get("disk_threshold", 90)
        
        data = {}
        error_msg = None
        success = True
        
        try:
            # 1. Hostname
            p_host = subprocess.run(hostname_command.split(), capture_output=True, text=True, timeout=timeout)
            data["hostname"] = p_host.stdout.strip() if p_host.returncode == 0 else f"Error (exit code {p_host.returncode}): {p_host.stderr.strip()}"
            
            # 2. OS Version
            p_os = subprocess.run(os_version_command.split(), capture_output=True, text=True, timeout=timeout)
            data["os_version"] = p_os.stdout.strip() if p_os.returncode == 0 else f"Error (exit code {p_os.returncode}): {p_os.stderr.strip()}"
            
            # 3. System Uptime
            p_uptime = subprocess.run(uptime_command.split(), capture_output=True, text=True, timeout=timeout)
            data["system_uptime"] = p_uptime.stdout.strip() if p_uptime.returncode == 0 else f"Error (exit code {p_uptime.returncode}): {p_uptime.stderr.strip()}"
            
            # 4. CPU Load
            p_cpu = subprocess.run(cpu_command.split(), capture_output=True, text=True, timeout=timeout)
            data["cpu"] = {
                "exit_code": p_cpu.returncode,
                "stdout": p_cpu.stdout.strip(),
                "stderr": p_cpu.stderr.strip()
            }
            
            # 5. Memory Statistics
            p_mem = subprocess.run(memory_command.split(), capture_output=True, text=True, timeout=timeout)
            data["memory"] = {
                "exit_code": p_mem.returncode,
                "stdout": p_mem.stdout.strip(),
                "stderr": p_mem.stderr.strip()
            }
            
            # 6. Disk Usage
            cmd = disk_command.split() + [disk_path]
            p_disk = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            
            disk_percent = None
            if p_disk.returncode == 0:
                lines = [l.strip() for l in p_disk.stdout.splitlines() if l.strip()]
                if len(lines) >= 2:
                    header_parts = lines[0].split()
                    capacity_idx = -1
                    for idx, part in enumerate(header_parts):
                        part_lower = part.lower()
                        if "capacity" in part_lower or "use%" in part_lower or part_lower == "cap" or part_lower == "use":
                            capacity_idx = idx
                            break
                    
                    for line in lines[1:]:
                        parts = line.split()
                        # 1. Primary: Try to parse using header-based index
                        if capacity_idx != -1 and len(parts) > capacity_idx:
                            val = parts[capacity_idx]
                            matches = re.findall(r'(\d+)%', val)
                            if matches:
                                disk_percent = int(matches[0])
                                break
                        
                        # 2. Fallback: Take the first percentage value found in the line
                        matches = re.findall(r'(\d+)%', line)
                        if matches:
                            disk_percent = int(matches[0])
                            break
                        
            data["disk"] = {
                "exit_code": p_disk.returncode,
                "stdout": p_disk.stdout.strip(),
                "stderr": p_disk.stderr.strip(),
                "parsed_usage_percent": disk_percent,
                "threshold_percent": disk_threshold,
                "threshold_exceeded": (disk_percent > disk_threshold) if disk_percent is not None else False
            }
            
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
