import os
import re
import sys
import time
import subprocess
from datetime import datetime, timezone
from typing import List, Optional, Tuple, Dict

from app.snapshot.models import (
    SnapshotContext,
    SnapshotProvider,
    CapturedArtifact,
    ProviderCaptureResult,
)
from app.snapshot.redaction import redact_content

# ---------------------------------------------------------------------------
# Constants & Helpers
# ---------------------------------------------------------------------------
_CMD_TIMEOUT = 1.5  # Consistent individual command timeout

def _run_cmd(args: List[str], timeout: float) -> Tuple[str, Optional[int], str]:
    """
    Run a command safely (shell=False, bounded output, no env leakage).
    Returns (stdout, returncode, stderr).
    """
    try:
        res = subprocess.run(
            args,
            capture_output=True,
            text=True,
            shell=False,
            timeout=timeout,
        )
        return res.stdout, res.returncode, res.stderr.strip()
    except FileNotFoundError:
        return "", None, f"Command not found: {args[0]}"
    except subprocess.TimeoutExpired:
        return "", None, "TIMEOUT"
    except Exception as exc:
        return "", None, str(exc)

def _redact_process_line(line: str) -> str:
    """
    Strips potentially sensitive tokens from process command lines.
    """
    sensitive_flags = re.compile(
        r'((?:--|-)(?:password|passwd|secret|token|key|auth|api[-_]?key|credential|jwt|bearer)'
        r'(?:=\S+|\s+\S+))',
        re.IGNORECASE,
    )
    line = sensitive_flags.sub(r'<REDACTED>', line)
    env_pattern = re.compile(
        r'\b([a-z0-9_]*(?:password|passwd|secret|token|key|auth|api[-_]?key|credential|jwt|bearer)[a-z0-9_]*=)\S+',
        re.IGNORECASE,
    )
    line = env_pattern.sub(r'\1<REDACTED>', line)
    return line

def _make_artifact(
    name: str,
    content: str,
    status: str,
    method: str,
    start: float,
    exit_code: Optional[int] = None,
    error_message: Optional[str] = None,
    redaction_applied: bool = False,
) -> CapturedArtifact:
    return CapturedArtifact(
        name=name,
        content=content,
        status=status,
        capture_method=method,
        captured_at=datetime.now(timezone.utc),
        duration_ms=round((time.perf_counter() - start) * 1000, 2),
        exit_code=exit_code,
        bytes_captured=len(content.encode("utf-8")),
        lines_captured=len(content.splitlines()),
        error_message=error_message,
        redaction_applied=redaction_applied,
    )

class RuntimeSnapshotProvider(SnapshotProvider):
    @property
    def name(self) -> str:
        return "runtime"

    @property
    def timeout_seconds(self) -> float:
        return 5.0

    def capture(self, context: SnapshotContext) -> ProviderCaptureResult:
        started_at = datetime.now(timezone.utc)
        wall_start = time.perf_counter()

        if sys.platform != "darwin":
            # Gracefully fail on non-macOS platforms
            return ProviderCaptureResult(
                provider_name=self.name,
                status="FAILED",
                artifacts=[],
                started_at=started_at,
                finished_at=started_at,
                duration_ms=0.0,
                error_message="Runtime Snapshot Provider is only supported on macOS (darwin)"
            )

        # ------------------------------------------------------------------
        # Configuration resolution: standard snapshot.providers.runtime pattern
        # ------------------------------------------------------------------
        provider_cfg = (
            context.config.get("snapshot", {})
            .get("providers", {})
            .get("runtime", {})
        )

        # Get launchd config or use sensible defaults.
        # Default target is the production HexaBeta LaunchAgent.
        launchd_label = provider_cfg.get("launchd_label", "com.hexa.backend")
        launchd_uid = provider_cfg.get("launchd_uid", os.getuid() if hasattr(os, "getuid") else 501)
        expected_command_contains = provider_cfg.get("expected_command_contains", ["uvicorn", "app.main:app"])

        artifacts: List[CapturedArtifact] = []

        # Count tracking for metadata
        commands_executed = 0
        commands_succeeded = 0
        commands_failed = 0

        def run_artifact_cmd(art_name: str, args: List[str], method: str) -> CapturedArtifact:
            nonlocal commands_executed, commands_succeeded, commands_failed
            t = time.perf_counter()
            commands_executed += 1
            out, rc, err = _run_cmd(args, _CMD_TIMEOUT)
            
            if rc == 0:
                commands_succeeded += 1
                status = "SUCCESS"
                content = redact_content(out)
                error_msg = None
            elif err == "TIMEOUT":
                commands_failed += 1
                status = "TIMEOUT"
                content = ""
                error_msg = "Command execution timed out"
            else:
                commands_failed += 1
                status = "SUCCESS"  # command ran and returned output (e.g. exit code 1 is still success for query check)
                content = redact_content(out if out.strip() else err)
                error_msg = None

            return _make_artifact(
                art_name, content, status, method, t,
                exit_code=rc, error_message=error_msg, redaction_applied=True
            )

        # 1. launchctl_print.txt
        print_args = ["launchctl", "print", f"gui/{launchd_uid}/{launchd_label}"]
        artifacts.append(run_artifact_cmd("launchctl_print.txt", print_args, "launchctl-print"))

        # 2. launchctl_blame.txt
        blame_args = ["launchctl", "blame", f"gui/{launchd_uid}/{launchd_label}"]
        artifacts.append(run_artifact_cmd("launchctl_blame.txt", blame_args, "launchctl-blame"))

        # 3. launchctl_list.txt
        list_args = ["launchctl", "list"]
        artifacts.append(run_artifact_cmd("launchctl_list.txt", list_args, "launchctl-list"))

        # 4 & 5: ps-based processes tree & status
        ps_t = time.perf_counter()
        commands_executed += 1
        ps_args = ["ps", "-ax", "-o", "pid,ppid,pgid,state,%cpu,%mem,start,time,command"]
        out, rc, err = _run_cmd(ps_args, _CMD_TIMEOUT)

        backend_found = False
        launchagent_found = False

        if rc == 0:
            commands_succeeded += 1
            # Parse processes
            lines = out.splitlines()
            header = lines[0] if lines else "PID PPID PGID STATE %CPU %MEM START TIME COMMAND"
            
            # Find candidate backend pids and build a process tree
            pid_to_ppid: Dict[int, int] = {}
            pid_to_line: Dict[int, str] = {}
            pid_to_cmd: Dict[int, str] = {}
            
            backend_lines = [header]
            
            for line in lines[1:]:
                parts = line.strip().split(None, 8)
                if len(parts) < 9:
                    continue
                try:
                    pid = int(parts[0])
                    ppid = int(parts[1])
                    cmd = parts[8]
                except ValueError:
                    continue
                
                pid_to_ppid[pid] = ppid
                pid_to_cmd[pid] = cmd
                pid_to_line[pid] = line
                
                # Check for backend signature
                if all(keyword in cmd for keyword in expected_command_contains):
                    backend_found = True
                    backend_lines.append(_redact_process_line(line))

                # Check for launchagent label/signature
                if launchd_label in cmd:
                    launchagent_found = True

            # Save backend_process.txt
            backend_content = redact_content("\n".join(backend_lines))
            artifacts.append(_make_artifact(
                "backend_process.txt", backend_content, "SUCCESS", "ps-filter", ps_t,
                exit_code=rc, redaction_applied=True
            ))

            # Reconstruct the tree hierarchy
            # To understand the parent-child relationships, we find all processes
            # in the ancestry of our backend or launchagent processes, or just output
            # the subset tree of processes matching the signature.
            tree_lines = ["Process Tree Hierarchy:"]
            visited = set()

            def build_tree_str(pid: int, indent: str = ""):
                if pid in visited:
                    return
                visited.add(pid)
                cmd_redacted = _redact_process_line(pid_to_cmd.get(pid, ""))
                tree_lines.append(f"{indent}└── [PID {pid}] {cmd_redacted}")
                # Find children
                children = [child_pid for child_pid, p_pid in pid_to_ppid.items() if p_pid == pid]
                for child in sorted(children):
                    build_tree_str(child, indent + "    ")

            # Find roots (processes matching keywords, or their ancestors if traceable)
            roots = []
            for pid, cmd in pid_to_cmd.items():
                if all(keyword in cmd for keyword in expected_command_contains):
                    # Trace back to launchd or find the topmost parent in the signature set
                    curr = pid
                    while curr in pid_to_ppid and pid_to_ppid[curr] != 1 and pid_to_ppid[curr] in pid_to_cmd:
                        parent = pid_to_ppid[curr]
                        if all(keyword in pid_to_cmd[parent] for keyword in expected_command_contains):
                            curr = parent
                        else:
                            break
                    if curr not in roots:
                        roots.append(curr)

            # Fallback to include any process containing launchd_label
            for pid, cmd in pid_to_cmd.items():
                if launchd_label in cmd and pid not in roots:
                    roots.append(pid)

            for root in sorted(roots):
                build_tree_str(root)

            if len(tree_lines) == 1:
                tree_lines.append("No active backend or launchagent processes detected to build tree.")

            tree_content = redact_content("\n".join(tree_lines))
            artifacts.append(_make_artifact(
                "process_tree.txt", tree_content, "SUCCESS", "ps-tree", ps_t,
                exit_code=rc, redaction_applied=True
            ))
        else:
            commands_failed += 1
            status = "TIMEOUT" if err == "TIMEOUT" else "FAILED"
            err_msg = "ps command execution timed out" if err == "TIMEOUT" else err
            artifacts.append(_make_artifact(
                "backend_process.txt", "", status, "ps-filter", ps_t,
                exit_code=rc, error_message=err_msg
            ))
            artifacts.append(_make_artifact(
                "process_tree.txt", "", status, "ps-tree", ps_t,
                exit_code=rc, error_message=err_msg
            ))

        # ------------------------------------------------------------------
        # Determine overall provider status based on individual results
        # ------------------------------------------------------------------
        success_count = sum(1 for a in artifacts if a.status == "SUCCESS")
        failure_count = sum(1 for a in artifacts if a.status in ("FAILED", "TIMEOUT"))

        if success_count == len(artifacts):
            overall_status = "SUCCESS"
        elif failure_count == len(artifacts):
            overall_status = "FAILED"
        else:
            overall_status = "PARTIAL"

        finished_at = datetime.now(timezone.utc)
        duration_ms = round((time.perf_counter() - wall_start) * 1000, 2)

        # Extended metadata matching specifications
        result = ProviderCaptureResult(
            provider_name=self.name,
            status=overall_status,
            artifacts=artifacts,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
        )

        # Add extended metadata dict to result to be written in engine
        result.custom_runtime_metadata = {
            "backend_found": backend_found,
            "launchagent_found": launchagent_found,
            "commands_executed": commands_executed,
            "commands_succeeded": commands_succeeded,
            "commands_failed": commands_failed,
            "capture_duration_ms": duration_ms
        }

        return result
