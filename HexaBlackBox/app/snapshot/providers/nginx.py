import os
import sys
import time
import subprocess
from datetime import datetime, timezone
from typing import List, Optional, Any
from app.snapshot.models import SnapshotContext, SnapshotProvider, CapturedArtifact, ProviderCaptureResult
from app.snapshot.redaction import redact_content
from app.snapshot.providers.utils import _tail_file

class NginxSnapshotProvider(SnapshotProvider):
    @property
    def name(self) -> str:
        return "nginx"

class MacOSNginxSnapshotProvider(NginxSnapshotProvider):
    def capture(self, context: SnapshotContext) -> ProviderCaptureResult:
        started_at = datetime.now(timezone.utc)
        start_time = time.perf_counter()
        
        provider_config = context.config.get("snapshot", {}).get("providers", {}).get("nginx", {})
        collectors_nginx = context.config.get("collectors", {}).get("nginx", {})
        
        # 1. Deduplicate Config: Fallback to collectors.nginx for Nginx specific paths
        logs_config = provider_config.get("logs", {})
        access_log_path = logs_config.get("access_log_path") or collectors_nginx.get("access_log_path", "/opt/homebrew/var/log/nginx/access.log")
        error_log_path = logs_config.get("error_log_path") or collectors_nginx.get("error_log_path", "/opt/homebrew/var/log/nginx/error.log")
        max_lines = logs_config.get("max_lines", 500)
        max_bytes = logs_config.get("max_bytes", 1048576)
        
        service_config = provider_config.get("service", {})
        nginx_binary = service_config.get("nginx_binary") or collectors_nginx.get("binary_path", "/opt/homebrew/bin/nginx")
        nginx_config = service_config.get("nginx_config") or collectors_nginx.get("config_path", "/opt/homebrew/etc/nginx/nginx.conf")
        
        network_config = provider_config.get("network", {})
        ports = network_config.get("ports", [80, 443])
        
        process_config = provider_config.get("process", {})
        expected_command_contains = process_config.get("expected_command_contains", ["nginx"])
        
        artifacts: List[CapturedArtifact] = []
        
        # Helper to tail and redact logs
        def capture_log(artifact_name: str, log_path: str) -> CapturedArtifact:
            log_start = time.perf_counter()
            try:
                content, truncated, lines_read, bytes_read = _tail_file(log_path, max_lines, max_bytes)
                if content == "" and os.path.exists(log_path):
                    # Ensure successfully inspected but empty logs still produce physical files
                    content = "Log file existed but was empty at snapshot time."
                    bytes_read = len(content.encode("utf-8"))
                    lines_read = 1
                try:
                    sanitized = redact_content(content)
                except Exception as re_err:
                    raise RuntimeError(f"Redaction failed: {re_err}")
                
                duration = round((time.perf_counter() - log_start) * 1000, 2)
                return CapturedArtifact(
                    name=artifact_name,
                    content=sanitized,
                    status="SUCCESS",
                    capture_method="file-tail",
                    captured_at=datetime.now(timezone.utc),
                    duration_ms=duration,
                    truncated=truncated,
                    bytes_captured=bytes_read,
                    lines_captured=lines_read,
                    redaction_applied=True
                )
            except Exception as e:
                duration = round((time.perf_counter() - log_start) * 1000, 2)
                return CapturedArtifact(
                    name=artifact_name,
                    content="",
                    status="FAILED",
                    capture_method="file-tail",
                    captured_at=datetime.now(timezone.utc),
                    duration_ms=duration,
                    error_message=str(e)
                )

        # Artifact 1: access.log
        artifacts.append(capture_log("access.log", access_log_path))
        
        # Artifact 2: error.log
        artifacts.append(capture_log("error.log", error_log_path))
        
        # Artifact 3: config_test.txt (Strictly timeout-bounded, validation only)
        test_start = time.perf_counter()
        try:
            test_cmd = [nginx_binary, "-t", "-c", nginx_config]
            res = subprocess.run(test_cmd, capture_output=True, text=True, shell=False, timeout=2.0)
            
            # nginx -t outputs configuration state to stderr
            output_content = res.stderr if res.stderr.strip() else res.stdout
            sanitized = redact_content(output_content)
            duration = round((time.perf_counter() - test_start) * 1000, 2)
            artifacts.append(CapturedArtifact(
                name="config_test.txt",
                content=sanitized,
                status="SUCCESS",
                capture_method="nginx-test",
                captured_at=datetime.now(timezone.utc),
                duration_ms=duration,
                exit_code=res.returncode,
                bytes_captured=len(sanitized.encode("utf-8")),
                lines_captured=len(sanitized.splitlines())
            ))
        except subprocess.TimeoutExpired:
            duration = round((time.perf_counter() - test_start) * 1000, 2)
            artifacts.append(CapturedArtifact(
                name="config_test.txt",
                content="",
                status="TIMEOUT",
                capture_method="nginx-test",
                captured_at=datetime.now(timezone.utc),
                duration_ms=duration,
                error_message="Configuration test timed out"
            ))
        except Exception as e:
            duration = round((time.perf_counter() - test_start) * 1000, 2)
            artifacts.append(CapturedArtifact(
                name="config_test.txt",
                content="",
                status="FAILED",
                capture_method="nginx-test",
                captured_at=datetime.now(timezone.utc),
                duration_ms=duration,
                error_message=str(e)
            ))

        # Artifact 4: processes.txt
        ps_start = time.perf_counter()
        try:
            ps_cmd = ["ps", "-ax", "-o", "pid,ppid,%cpu,%mem,command"]
            res = subprocess.run(ps_cmd, capture_output=True, text=True, shell=False, timeout=1.0)
            self_pid = os.getpid()
            lines = res.stdout.splitlines()
            header = lines[0] if lines else "PID PPID %CPU %MEM COMMAND"
            
            filtered_lines = [header]
            for line in lines[1:]:
                match = any(term in line for term in expected_command_contains)
                if match:
                    parts = line.strip().split()
                    if parts:
                        pid = int(parts[0])
                        if pid != self_pid:
                            filtered_lines.append(line)
                            
            sanitized = redact_content("\n".join(filtered_lines))
            duration = round((time.perf_counter() - ps_start) * 1000, 2)
            artifacts.append(CapturedArtifact(
                name="processes.txt",
                content=sanitized,
                status="SUCCESS",
                capture_method="ps-filter",
                captured_at=datetime.now(timezone.utc),
                duration_ms=duration,
                exit_code=res.returncode,
                bytes_captured=len(sanitized.encode("utf-8")),
                lines_captured=len(sanitized.splitlines())
            ))
        except subprocess.TimeoutExpired:
            duration = round((time.perf_counter() - ps_start) * 1000, 2)
            artifacts.append(CapturedArtifact(
                name="processes.txt",
                content="",
                status="TIMEOUT",
                capture_method="ps-filter",
                captured_at=datetime.now(timezone.utc),
                duration_ms=duration,
                error_message="Process collection timed out"
            ))
        except Exception as e:
            duration = round((time.perf_counter() - ps_start) * 1000, 2)
            artifacts.append(CapturedArtifact(
                name="processes.txt",
                content="",
                status="FAILED",
                capture_method="ps-filter",
                captured_at=datetime.now(timezone.utc),
                duration_ms=duration,
                error_message=str(e)
            ))

        # Artifact 5: ports.txt
        port_start = time.perf_counter()
        port_outputs = []
        port_status = "SUCCESS"
        port_method = "lsof-port"
        
        for port in ports:
            try:
                port_cmd = ["lsof", "-n", "-P", "-i", f"tcp:{port}"]
                res = subprocess.run(port_cmd, capture_output=True, text=True, shell=False, timeout=1.0)
                if res.returncode == 0 and res.stdout.strip():
                    port_outputs.append(f"=== Port {port} Listening ===\n" + redact_content(res.stdout))
                else:
                    port_outputs.append(f"Port: {port}\nListening: false\nListener: none\n")
            except subprocess.TimeoutExpired:
                port_outputs.append(f"=== Port {port} Check Timeout ===\n")
                port_status = "TIMEOUT"
            except Exception as e:
                port_outputs.append(f"=== Port {port} Check Failed: {e} ===\n")
                port_status = "FAILED"
                
        port_content = "\n".join(port_outputs)
        port_duration = round((time.perf_counter() - port_start) * 1000, 2)
        artifacts.append(CapturedArtifact(
            name="ports.txt",
            content=port_content,
            status=port_status,
            capture_method=port_method,
            captured_at=datetime.now(timezone.utc),
            duration_ms=port_duration,
            bytes_captured=len(port_content.encode("utf-8")),
            lines_captured=len(port_content.splitlines())
        ))

        # Calculate overall provider status
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

class LinuxNginxSnapshotProvider(NginxSnapshotProvider):
    def capture(self, context: SnapshotContext) -> ProviderCaptureResult:
        started_at = datetime.now(timezone.utc)
        return ProviderCaptureResult(
            provider_name=self.name,
            status="FAILED",
            artifacts=[],
            started_at=started_at,
            finished_at=started_at,
            duration_ms=0.0,
            error_message="Linux Nginx provider not implemented in this batch"
        )
