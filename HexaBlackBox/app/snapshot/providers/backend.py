import os
import sys
import time
import subprocess
from datetime import datetime, timezone
from typing import List, Optional, Any
from app.snapshot.models import SnapshotContext, SnapshotProvider, CapturedArtifact, ProviderCaptureResult
from app.snapshot.redaction import redact_content

def _tail_file(path: str, max_lines: int, max_bytes: int) -> tuple[str, bool, int, int]:
    """
    Forensically tails a log file, seeking backwards from the end to limit memory consumption.
    Returns (content, truncated, lines_read, bytes_read).
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")
    if not os.access(path, os.R_OK):
        raise PermissionError(f"File not readable: {path}")
        
    file_size = os.path.getsize(path)
    if file_size == 0:
        return "", False, 0, 0
        
    read_size = min(max_bytes, file_size)
    
    with open(path, "rb") as f:
        f.seek(-read_size, os.SEEK_END)
        raw_data = f.read(read_size)
        
    decoded = raw_data.decode("utf-8", errors="ignore")
    lines = decoded.splitlines()
    
    truncated = (file_size > max_bytes)
    
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
        truncated = True
        
    content = "\n".join(lines)
    bytes_captured = len(content.encode("utf-8"))
    return content, truncated, len(lines), bytes_captured


class BackendSnapshotProvider(SnapshotProvider):
    @property
    def name(self) -> str:
        return "backend"


class MacOSBackendSnapshotProvider(BackendSnapshotProvider):
    def capture(self, context: SnapshotContext) -> ProviderCaptureResult:
        started_at = datetime.now(timezone.utc)
        start_time = time.perf_counter()
        
        provider_config = context.config.get("snapshot", {}).get("providers", {}).get("backend", {})
        
        # 1. Config paths & limits
        logs_config = provider_config.get("logs", {})
        stdout_path = logs_config.get("stdout_path", "/Users/hexabeta/backend.log")
        stderr_path = logs_config.get("stderr_path", "/Users/hexabeta/backend-error.log")
        max_lines = logs_config.get("max_lines", 500)
        max_bytes = logs_config.get("max_bytes", 1048576)
        
        service_config = provider_config.get("service", {})
        launchd_label = service_config.get("launchd_label", "com.hexa.backend")
        # launchd_uid must match the GUI session user that owns the LaunchAgent.
        # On macOS this is typically the UID of the logged-in user (e.g. 501),
        # which may differ from the UID of the process running HexaBlackBox.
        # Configure service.launchd_uid in config.yaml to set this explicitly.
        launchd_uid = service_config.get("launchd_uid", os.getuid() if hasattr(os, "getuid") else 501)
        
        network_config = provider_config.get("network", {})
        port = network_config.get("port", 8002)
        
        process_config = provider_config.get("process", {})
        expected_command_contains = process_config.get("expected_command_contains", ["uvicorn", "app.main:app"])
        
        artifacts: List[CapturedArtifact] = []
        
        # Helper to execute shell commands read-only
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

        # Artifact 1: stdout.log
        stdout_start = time.perf_counter()
        try:
            content, truncated, lines_read, bytes_read = _tail_file(stdout_path, max_lines, max_bytes)
            try:
                sanitized = redact_content(content)
            except Exception as re_err:
                raise RuntimeError(f"Redaction failed: {re_err}")
                
            duration = round((time.perf_counter() - stdout_start) * 1000, 2)
            artifacts.append(CapturedArtifact(
                name="stdout.log",
                content=sanitized,
                status="SUCCESS",
                capture_method="file-tail",
                captured_at=datetime.now(timezone.utc),
                duration_ms=duration,
                truncated=truncated,
                bytes_captured=bytes_read,
                lines_captured=lines_read,
                redaction_applied=True
            ))
        except Exception as e:
            duration = round((time.perf_counter() - stdout_start) * 1000, 2)
            artifacts.append(CapturedArtifact(
                name="stdout.log",
                content="",
                status="FAILED",
                capture_method="file-tail",
                captured_at=datetime.now(timezone.utc),
                duration_ms=duration,
                error_message=str(e)
            ))

        # Artifact 2: stderr.log
        stderr_start = time.perf_counter()
        try:
            content, truncated, lines_read, bytes_read = _tail_file(stderr_path, max_lines, max_bytes)
            try:
                sanitized = redact_content(content)
            except Exception as re_err:
                raise RuntimeError(f"Redaction failed: {re_err}")
                
            duration = round((time.perf_counter() - stderr_start) * 1000, 2)
            artifacts.append(CapturedArtifact(
                name="stderr.log",
                content=sanitized,
                status="SUCCESS",
                capture_method="file-tail",
                captured_at=datetime.now(timezone.utc),
                duration_ms=duration,
                truncated=truncated,
                bytes_captured=bytes_read,
                lines_captured=lines_read,
                redaction_applied=True
            ))
        except Exception as e:
            duration = round((time.perf_counter() - stderr_start) * 1000, 2)
            artifacts.append(CapturedArtifact(
                name="stderr.log",
                content="",
                status="FAILED",
                capture_method="file-tail",
                captured_at=datetime.now(timezone.utc),
                duration_ms=duration,
                error_message=str(e)
            ))

        # Artifact 3: launchd.txt
        # Use the configured launchd_uid (resolved at config load time above).
        # If the service is unloaded after hb-stop, launchctl will report it as
        # missing — that output is preserved verbatim as valid forensic evidence.
        launchd_cmd = ["launchctl", "print", f"gui/{launchd_uid}/{launchd_label}"]
        artifacts.append(run_cmd("launchd.txt", launchd_cmd, "launchctl-print"))

        # Artifact 4: processes.txt
        ps_start = time.perf_counter()
        try:
            ps_cmd = ["ps", "-ax", "-o", "pid,ppid,%cpu,%mem,command"]
            res = subprocess.run(ps_cmd, capture_output=True, text=True, shell=False, timeout=1.0)
            
            # Parse processes in Python (no grep) to avoid false-positives
            self_pid = os.getpid()
            lines = res.stdout.splitlines()
            header = lines[0] if lines else "PID PPID %CPU %MEM COMMAND"
            
            filtered_lines = [header]
            for line in lines[1:]:
                # Check for signatures
                match = all(term in line for term in expected_command_contains)
                if match:
                    # Parse PID
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

        # Artifact 5: port.txt
        # lsof exits with code 1 and empty output when nothing listens on the port.
        # "No listener" is a successful forensic observation — not a failure.
        # We always produce content so port.txt is always written to disk.
        port_start = time.perf_counter()
        try:
            port_cmd = ["lsof", "-n", "-P", "-i", f"tcp:{port}"]
            res = subprocess.run(port_cmd, capture_output=True, text=True, shell=False, timeout=1.0)
            duration = round((time.perf_counter() - port_start) * 1000, 2)

            if res.returncode == 0 and res.stdout.strip():
                # Listener found — capture the raw lsof output.
                sanitized = redact_content(res.stdout)
                port_content = sanitized
                port_note = "listener-found"
            else:
                # lsof exited with 1 (no match) or returned empty output.
                # This is a successful read: nothing is listening.
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

        # Determine overall provider status based on individual results
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


class LinuxBackendSnapshotProvider(BackendSnapshotProvider):
    def capture(self, context: SnapshotContext) -> ProviderCaptureResult:
        # Stub implementation for future Linux deployments
        started_at = datetime.now(timezone.utc)
        return ProviderCaptureResult(
            provider_name=self.name,
            status="FAILED",
            artifacts=[],
            started_at=started_at,
            finished_at=started_at,
            duration_ms=0.0,
            error_message="Linux provider not implemented in this batch"
        )
