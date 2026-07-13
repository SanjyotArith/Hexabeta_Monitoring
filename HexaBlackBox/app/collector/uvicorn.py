import subprocess
import time
import os
import re
from datetime import datetime
from app.collector import BaseCollector
from app.evidence import CollectorResult

class UvicornCollector(BaseCollector):
    def collect(self, config: dict) -> CollectorResult:
        started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        start_time = time.perf_counter()
        
        service_label = config.get("service_label")
        port = config.get("port")
        expected_workers = config.get("expected_workers")
        
        data = {}
        error_msg = None
        success = True
        
        try:
            # 1. Query launchd to get launchd PID if running
            p_launchctl = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=5)
            launchd_pid = None
            registered = False
            
            if p_launchctl.returncode == 0:
                for line in p_launchctl.stdout.splitlines():
                    if service_label in line:
                        registered = True
                        parts = line.strip().split()
                        if parts and parts[0].isdigit():
                            launchd_pid = int(parts[0])
                        break
                        
            data["launchd_status"] = {
                "label": service_label,
                "registered": registered,
                "launchd_pid": launchd_pid
            }
            
            # 2. Get process list using ps
            p_ps = subprocess.run(["ps", "-ax", "-o", "pid,ppid,lstart,command"], capture_output=True, text=True, timeout=5)
            
            processes = []
            if p_ps.returncode == 0:
                lines = p_ps.stdout.splitlines()
                for line in lines[1:]:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    parts = stripped.split(None, 7)
                    if len(parts) < 8:
                        continue
                    
                    pid_str, ppid_str, day, month, date, time_str, year, cmd = parts
                    pid = int(pid_str)
                    ppid = int(ppid_str)
                    
                    # Uniquely identify production backend using port AND service_label
                    port_pattern = f":{port}"
                    port_space_pattern = f" {port}"
                    port_eq_pattern = f"port={port}"
                    
                    has_port = (port_pattern in cmd) or (port_space_pattern in cmd) or (port_eq_pattern in cmd)
                    has_label = (service_label in cmd) or (pid == launchd_pid or ppid == launchd_pid)
                    
                    # Check exclusions
                    cmd_lower = cmd.lower()
                    should_ignore = ("uat" in cmd_lower) or ("agent" in cmd_lower) or ("oir" in cmd_lower)
                    
                    # Match if:
                    # - It has both port and label (strongest match)
                    # - OR it matches launchd PID
                    # - OR it has port and does not have ignore labels (fallback)
                    is_production_backend = False
                    if has_port and has_label and not should_ignore:
                        is_production_backend = True
                    elif launchd_pid is not None and (pid == launchd_pid or ppid == launchd_pid):
                        is_production_backend = True
                    elif has_port and not should_ignore:
                        is_production_backend = True
                        
                    if is_production_backend:
                        processes.append({
                            "pid": pid,
                            "ppid": ppid,
                            "start_time_str": f"{day} {month} {date} {time_str} {year}",
                            "command": cmd
                        })
            
            if not processes:
                data["running"] = False
                data["pid"] = None
                data["worker_count"] = 0
                data["command_line"] = None
                data["port"] = port
                data["uptime_seconds"] = 0
            else:
                data["running"] = True
                
                # Identify master process (usually the one with PPID that is not in the list, or PPID == 1, or PPID == launchd PID)
                pids = {p["pid"] for p in processes}
                master = None
                for p in processes:
                    if p["ppid"] not in pids:
                        master = p
                        break
                if not master:
                    master = processes[0]
                    
                data["pid"] = master["pid"]
                data["command_line"] = master["command"]
                data["port"] = port
                
                # Workers are child processes (PPID == master PID)
                workers = [p for p in processes if p["ppid"] == master["pid"]]
                data["worker_count"] = len(workers)
                
                # Calculate uptime
                try:
                    clean_date_str = " ".join(master["start_time_str"].split())
                    start_dt = datetime.strptime(clean_date_str, "%a %b %d %H:%M:%S %Y")
                    data["uptime_seconds"] = int((datetime.now() - start_dt).total_seconds())
                except Exception:
                    data["uptime_seconds"] = None
                    
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
