import subprocess
import time
from datetime import datetime
from app.collector import BaseCollector
from app.evidence import CollectorResult

class LaunchctlCollector(BaseCollector):
    def collect(self, config: dict) -> CollectorResult:
        started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        start_time = time.perf_counter()
        
        timeout = config.get("timeout", 5)
        services = config.get("services", [])
        
        data = {}
        error_msg = None
        success = True
        
        try:
            # 1. Query launchctl list
            p_launchctl = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=timeout)
            
            services_status = {}
            for svc in services:
                services_status[svc] = {
                    "registered": False,
                    "running": False,
                    "pid": None,
                    "last_exit_code": None,
                    "details": None,
                    "details_warning": None
                }
                
            if p_launchctl.returncode == 0:
                for line in p_launchctl.stdout.splitlines():
                    line_stripped = line.strip()
                    if not line_stripped:
                        continue
                    parts = line_stripped.split()
                    if len(parts) < 3:
                        continue
                    pid_str, status_str, label = parts[0], parts[1], parts[2]
                    
                    if label in services_status:
                        services_status[label]["registered"] = True
                        if pid_str.isdigit():
                            services_status[label]["running"] = True
                            services_status[label]["pid"] = int(pid_str)
                        if status_str.lstrip('-').isdigit():
                            services_status[label]["last_exit_code"] = int(status_str)
                            
            # 2. Get deeper launchctl details for registered services
            for svc in services:
                if services_status[svc]["registered"]:
                    try:
                        p_details = subprocess.run(["launchctl", "list", svc], capture_output=True, text=True, timeout=timeout)
                        if p_details.returncode == 0:
                            services_status[svc]["details"] = p_details.stdout.strip()
                        else:
                            services_status[svc]["details_warning"] = f"launchctl list {svc} returned exit code {p_details.returncode}: {p_details.stderr.strip()}"
                    except Exception as details_err:
                        services_status[svc]["details_warning"] = str(details_err)
                        
            data["services"] = services_status
            
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
