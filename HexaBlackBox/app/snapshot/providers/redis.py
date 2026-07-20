import os
import sys
import time
import subprocess
from datetime import datetime, timezone
from typing import List, Optional, Tuple, Dict
from app.snapshot.models import SnapshotContext, SnapshotProvider, CapturedArtifact, ProviderCaptureResult
from app.snapshot.redaction import redact_content


def _token_match_process(command_field: str, signatures: List[str]) -> bool:
    """
    Checks if all signature terms match complete tokens or basenames in the command field.
    """
    if not command_field or not signatures:
        return False
    tokens = command_field.strip().split()
    if not tokens:
        return False
    argv0_basename = os.path.basename(tokens[0])
    matchable = set(tokens) | {argv0_basename}
    for term in signatures:
        if term not in matchable:
            return False
    return True


class RedisSnapshotProvider(SnapshotProvider):
    @property
    def name(self) -> str:
        return "redis"


class MacOSRedisSnapshotProvider(RedisSnapshotProvider):
    def capture(self, context: SnapshotContext) -> ProviderCaptureResult:
        started_at = datetime.now(timezone.utc)
        start_time = time.perf_counter()

        # Resolve configuration with fallback precedence
        provider_config = (
            context.config.get("snapshot", {})
            .get("providers", {})
            .get("redis", {})
        )
        collectors_redis = context.config.get("collectors", {}).get("redis", {})

        enabled = provider_config.get("enabled", True)
        host = provider_config.get("host") or collectors_redis.get("host", "localhost")
        port = provider_config.get("port") or collectors_redis.get("port", 6379)
        password = provider_config.get("password") or collectors_redis.get("password", "")
        binary_path = provider_config.get("binary_path") or collectors_redis.get("binary_path", "redis-cli")
        timeout_val = float(provider_config.get("timeout", collectors_redis.get("timeout", 5.0)))
        slowlog_count = int(provider_config.get("slowlog_count", 10))

        artifacts: List[CapturedArtifact] = []

        # Prepare env for subprocess authentication safety
        env = os.environ.copy()
        if password:
            env["REDISCLI_AUTH"] = password

        # Helper to execute redis-cli commands safely
        def run_redis_cmd(args: List[str], timeout: float) -> Tuple[str, Optional[int], str, str]:
            """
            Executes redis-cli with the given arguments, avoiding exposing credentials.
            Returns (stdout_content, exit_code, status, error_message).
            """
            # Do NOT pass host/port if they are empty, but construct arguments list safely
            cmd = [binary_path, "-h", host, "-p", str(port)] + args
            try:
                res = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    shell=False,
                    timeout=timeout,
                    env=env
                )
                return res.stdout, res.returncode, "SUCCESS", res.stderr
            except FileNotFoundError:
                return "", None, "FAILED", f"Redis CLI binary not found at: {binary_path}"
            except subprocess.TimeoutExpired:
                return "", None, "TIMEOUT", "Command execution timed out"
            except Exception as e:
                return "", None, "FAILED", str(e)

        # Artifact 1: redis_processes.txt
        ps_start = time.perf_counter()
        try:
            ps_cmd = ["ps", "-ax", "-o", "pid,ppid,%cpu,%mem,command"]
            res = subprocess.run(ps_cmd, capture_output=True, text=True, shell=False, timeout=1.0)
            self_pid = os.getpid()
            lines = res.stdout.splitlines()
            header = lines[0] if lines else "PID PPID %CPU %MEM COMMAND"

            filtered = [header]
            for line in lines[1:]:
                parts = line.strip().split(None, 4)
                if len(parts) < 5:
                    continue
                try:
                    pid = int(parts[0])
                except ValueError:
                    continue
                if pid == self_pid:
                    continue
                command_field = parts[4]
                if _token_match_process(command_field, ["redis-server"]):
                    filtered.append(line)

            if len(filtered) == 1:
                filtered.append("redis-server: No matching processes found at snapshot time.")

            content = redact_content("\n".join(filtered))
            artifacts.append(CapturedArtifact(
                name="redis_processes.txt",
                content=content,
                status="SUCCESS",
                capture_method="ps-token-filter",
                captured_at=datetime.now(timezone.utc),
                duration_ms=round((time.perf_counter() - ps_start) * 1000, 2),
                bytes_captured=len(content.encode("utf-8")),
                lines_captured=len(content.splitlines())
            ))
        except subprocess.TimeoutExpired:
            artifacts.append(CapturedArtifact(
                name="redis_processes.txt",
                content="",
                status="TIMEOUT",
                capture_method="ps-token-filter",
                captured_at=datetime.now(timezone.utc),
                duration_ms=round((time.perf_counter() - ps_start) * 1000, 2),
                error_message="ps command timed out"
            ))
        except Exception as e:
            artifacts.append(CapturedArtifact(
                name="redis_processes.txt",
                content="",
                status="FAILED",
                capture_method="ps-token-filter",
                captured_at=datetime.now(timezone.utc),
                duration_ms=round((time.perf_counter() - ps_start) * 1000, 2),
                error_message=str(e)
            ))

        # Artifact 2: port.txt (local LISTEN only)
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
            artifacts.append(CapturedArtifact(
                name="port.txt",
                content="",
                status="TIMEOUT",
                capture_method="lsof-port",
                captured_at=datetime.now(timezone.utc),
                duration_ms=round((time.perf_counter() - port_start) * 1000, 2),
                error_message="lsof command timed out"
            ))
        except Exception as e:
            artifacts.append(CapturedArtifact(
                name="port.txt",
                content="",
                status="FAILED",
                capture_method="lsof-port",
                captured_at=datetime.now(timezone.utc),
                duration_ms=round((time.perf_counter() - port_start) * 1000, 2),
                error_message=str(e)
            ))

        # Helper to extract sections from raw Redis INFO command response
        def get_info_section(info_output: str, sections_to_keep: List[str]) -> str:
            lines = info_output.splitlines()
            result_lines = []
            current_section = None
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("#"):
                    current_section = stripped[1:].strip().lower()
                    if current_section in sections_to_keep:
                        result_lines.append(line)
                elif current_section in sections_to_keep and stripped:
                    result_lines.append(line)
            return "\n".join(result_lines)

        # Artifact 3: connectivity.txt
        conn_start = time.perf_counter()
        stdout_raw, exit_code, status, err_msg = run_redis_cmd(["PING"], timeout_val)
        conn_duration = round((time.perf_counter() - conn_start) * 1000, 2)
        
        is_reachable = False
        if status == "SUCCESS":
            response = stdout_raw.strip()
            # Mask or check authentication errors safely
            if "NOAUTH" in response or "NOAUTH" in err_msg:
                connectivity_content = (
                    f"Host: {host}\n"
                    f"Port: {port}\n"
                    f"Connection: FAILED\n"
                    f"Reason: Authentication required or invalid password\n"
                )
            elif exit_code == 0 and "PONG" in response:
                connectivity_content = (
                    f"Host: {host}\n"
                    f"Port: {port}\n"
                    f"Connection: SUCCESS\n"
                    f"Response: PONG\n"
                )
                is_reachable = True
            else:
                combined_err = redact_content((stdout_raw + "\n" + err_msg).strip())
                connectivity_content = (
                    f"Host: {host}\n"
                    f"Port: {port}\n"
                    f"Connection: FAILED\n"
                    f"Reason: {combined_err}\n"
                )
        else:
            connectivity_content = (
                f"Host: {host}\n"
                f"Port: {port}\n"
                f"Connection: FAILED\n"
                f"Reason: {err_msg}\n"
            )

        artifacts.append(CapturedArtifact(
            name="connectivity.txt",
            content=connectivity_content,
            status=status,
            capture_method="redis-ping",
            captured_at=datetime.now(timezone.utc),
            duration_ms=conn_duration,
            exit_code=exit_code,
            bytes_captured=len(connectivity_content.encode("utf-8")),
            lines_captured=len(connectivity_content.splitlines())
        ))

        # Define all metrics diagnostics keys for filtering
        info_raw = ""
        info_err_msg = ""
        info_status = "SUCCESS"

        if is_reachable:
            # Query the Redis INFO to extract database metrics
            info_start = time.perf_counter()
            stdout_info, exit_code_info, status_info, err_info = run_redis_cmd(["INFO"], timeout_val)
            if status_info == "SUCCESS" and exit_code_info == 0:
                info_raw = stdout_info
            else:
                info_status = status_info
                info_err_msg = err_info or "Failed to query INFO"
        else:
            info_status = "FAILED"
            info_err_msg = "Skipped system queries: Redis is unreachable"

        # Helper to append info-based section artifacts
        def add_info_artifact(name: str, sections: List[str]):
            if info_status == "SUCCESS":
                sec_content = redact_content(get_info_section(info_raw, sections))
                art_status = "SUCCESS"
                art_err = None
            else:
                sec_content = info_err_msg
                art_status = "FAILED"
                art_err = info_err_msg

            artifacts.append(CapturedArtifact(
                name=name,
                content=sec_content,
                status=art_status,
                capture_method="redis-info",
                captured_at=datetime.now(timezone.utc),
                duration_ms=round((time.perf_counter() - conn_start) * 1000, 2),
                error_message=art_err,
                bytes_captured=len(sec_content.encode("utf-8")),
                lines_captured=len(sec_content.splitlines())
            ))

        # Artifact 4: info.txt (server, persistence, replication, keyspace)
        add_info_artifact("info.txt", ["server", "persistence", "replication", "keyspace"])

        # Artifact 5: memory.txt (memory section)
        add_info_artifact("memory.txt", ["memory"])

        # Artifact 6: clients.txt (clients section)
        add_info_artifact("clients.txt", ["clients"])

        # Artifact 7: stats.txt (stats section)
        add_info_artifact("stats.txt", ["stats"])

        # Artifact 8: slowlog.txt (SLOWLOG GET count)
        slow_content = ""
        slow_status = "SUCCESS"
        slow_err = None

        if is_reachable:
            slow_start = time.perf_counter()
            # Fetch slow log entries
            stdout_slow, exit_code_slow, status_slow, err_slow = run_redis_cmd(["SLOWLOG", "GET", str(slowlog_count)], timeout_val)
            if status_slow == "SUCCESS" and exit_code_slow == 0:
                import re
                raw_entries = stdout_slow.splitlines()
                entries = []
                current_entry = {}
                
                for line in raw_entries:
                    line_str = line.strip()
                    # Match Entry ID (e.g. "1) 1) (integer) 1" or "1) (integer) 1")
                    id_match = re.search(r'(?:^\d+\)\s+)?1\)\s+\(integer\)\s+(\d+)', line_str)
                    if id_match:
                        if current_entry:
                            entries.append(current_entry)
                        current_entry = {"id": id_match.group(1), "timestamp": None, "duration": None, "command": None}
                        continue
                    if not current_entry:
                        continue
                    # Match timestamp
                    ts_match = re.search(r'2\)\s+\(integer\)\s+(\d+)', line_str)
                    if ts_match:
                        current_entry["timestamp"] = ts_match.group(1)
                        continue
                    # Match duration
                    dur_match = re.search(r'3\)\s+\(integer\)\s+(\d+)', line_str)
                    if dur_match:
                        current_entry["duration"] = dur_match.group(1)
                        continue
                    # Match command name (first argument list item)
                    cmd_match = re.search(r'4\)\s+1\)\s+["\']?([^"\']+)["\']?', line_str)
                    if cmd_match:
                        current_entry["command"] = cmd_match.group(1)
                        continue
                        
                if current_entry:
                    entries.append(current_entry)
                    
                formatted_entries = []
                for entry in entries:
                    eid = entry.get("id") or "UNKNOWN"
                    raw_ts = entry.get("timestamp")
                    if raw_ts:
                        try:
                            ts = datetime.fromtimestamp(int(raw_ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                        except Exception:
                            ts = "UNKNOWN"
                    else:
                        ts = "UNKNOWN"
                        
                    raw_dur = entry.get("duration")
                    if raw_dur:
                        try:
                            dur_ms = round(float(raw_dur) / 1000.0, 2)
                            dur = f"{dur_ms} ms"
                        except Exception:
                            dur = "UNKNOWN"
                    else:
                        dur = "UNKNOWN"
                        
                    cmd = entry.get("command") or "UNKNOWN"
                    
                    formatted_entries.append(
                        f"Entry ID: {eid}\n"
                        f"Timestamp: {ts}\n"
                        f"Duration: {dur}\n"
                        f"Command: {cmd}\n"
                        f"Arguments: <REDACTED>\n"
                    )
                slow_content = "\n".join(formatted_entries)
                if not slow_content.strip():
                    slow_content = "Slow log is empty."
            else:
                slow_status = status_slow
                slow_err = err_slow
        else:
            slow_content = info_err_msg
            slow_status = "FAILED"
            slow_err = info_err_msg

        artifacts.append(CapturedArtifact(
            name="slowlog.txt",
            content=slow_content,
            status=slow_status,
            capture_method="redis-slowlog",
            captured_at=datetime.now(timezone.utc),
            duration_ms=round((time.perf_counter() - conn_start) * 1000, 2),
            error_message=slow_err,
            bytes_captured=len(slow_content.encode("utf-8")),
            lines_captured=len(slow_content.splitlines())
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


class LinuxRedisSnapshotProvider(RedisSnapshotProvider):
    """Stub implementation for Linux environments."""
    def capture(self, context: SnapshotContext) -> ProviderCaptureResult:
        started_at = datetime.now(timezone.utc)
        return ProviderCaptureResult(
            provider_name=self.name,
            status="FAILED",
            artifacts=[],
            started_at=started_at,
            finished_at=started_at,
            duration_ms=0.0,
            error_message="Linux Redis provider not implemented in this batch"
        )
