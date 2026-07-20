import os
import re
import sys
import time
import subprocess
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from app.snapshot.models import (
    SnapshotContext,
    SnapshotProvider,
    CapturedArtifact,
    ProviderCaptureResult,
)
from app.snapshot.redaction import redact_content


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------
_MAX_OUTPUT_BYTES = 65536   # 64 KB hard cap per artifact
_MAX_LINES = 200            # hard cap on output lines per artifact


def _run_cmd(
    args: List[str],
    timeout: float,
    max_bytes: int = _MAX_OUTPUT_BYTES,
) -> Tuple[str, Optional[int], str]:
    """
    Run a command safely (shell=False, bounded output, no env leakage).
    Returns (stdout_truncated, returncode_or_None, error_message).
    """
    try:
        res = subprocess.run(
            args,
            capture_output=True,
            text=True,
            shell=False,
            timeout=timeout,
        )
        out = res.stdout
        if len(out.encode("utf-8")) > max_bytes:
            out = out.encode("utf-8")[:max_bytes].decode("utf-8", errors="replace") + "\n... [TRUNCATED]"
        return out, res.returncode, res.stderr.strip()
    except FileNotFoundError:
        return "", None, f"Command not found: {args[0]}"
    except subprocess.TimeoutExpired:
        return "", None, "TIMEOUT"
    except Exception as exc:
        return "", None, str(exc)


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


def _failed_artifact(
    name: str,
    method: str,
    start: float,
    error_message: str,
    status: str = "FAILED",
) -> CapturedArtifact:
    return _make_artifact(name, "", status, method, start, error_message=error_message)


def _redact_process_line(line: str) -> str:
    """
    Strips potentially sensitive tokens from a single process command line.
    Specifically removes anything that looks like a flag value carrying a
    secret (--password=X, -p X, --token X, PGPASSWORD=X, etc.).
    The resulting line retains the process name and non-secret flags.
    """
    # Remove --flag=VALUE and --flag VALUE patterns for sensitive flag names
    sensitive_flags = re.compile(
        r'((?:--|-)(?:password|passwd|secret|token|key|auth|api[-_]?key|credential|jwt|bearer)'
        r'(?:=\S+|\s+\S+))',
        re.IGNORECASE,
    )
    line = sensitive_flags.sub(r'<REDACTED>', line)
    # Remove bare environment variable assignments embedded in ps COMMAND
    env_pattern = re.compile(
        r'\b([a-z0-9_]*(?:password|passwd|secret|token|key|auth|api[-_]?key|credential|jwt|bearer)[a-z0-9_]*=)\S+',
        re.IGNORECASE,
    )
    line = env_pattern.sub(r'\1<REDACTED>', line)
    return line


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------
class SystemSnapshotProvider(SnapshotProvider):
    @property
    def name(self) -> str:
        return "system"


# ---------------------------------------------------------------------------
# macOS implementation
# ---------------------------------------------------------------------------
class MacOSSystemSnapshotProvider(SystemSnapshotProvider):

    def capture(self, context: SnapshotContext) -> ProviderCaptureResult:
        started_at = datetime.now(timezone.utc)
        wall_start = time.perf_counter()

        # ------------------------------------------------------------------
        # Configuration resolution: snapshot.providers.system > collectors.system
        # ------------------------------------------------------------------
        provider_cfg = (
            context.config.get("snapshot", {})
            .get("providers", {})
            .get("system", {})
        )
        collectors_cfg = context.config.get("collectors", {}).get("system", {})

        cmd_timeout = float(
            provider_cfg.get("timeout")
            or collectors_cfg.get("timeout", 5.0)
        )
        disk_paths: List[str] = (
            provider_cfg.get("disk_paths")
            or [collectors_cfg.get("disk_path", "/")]
        )
        top_process_count = int(
            provider_cfg.get("top_process_count")
            or collectors_cfg.get("top_process_count", 15)
        )
        # Clamp to a safe bound
        top_process_count = min(max(top_process_count, 1), 50)

        artifacts: List[CapturedArtifact] = []
        self_pid = os.getpid()

        # ==================================================================
        # Artifact 1 — system_info.txt
        # Hostname, macOS version (sw_vers), uname -a, architecture
        # ==================================================================
        t = time.perf_counter()
        try:
            lines = []

            # hostname
            out, rc, err = _run_cmd(["hostname"], timeout=cmd_timeout)
            lines.append(f"Hostname: {out.strip() or '(unknown)'}")

            # sw_vers (macOS-specific product info)
            out, rc, err = _run_cmd(["sw_vers"], timeout=cmd_timeout)
            lines.append("\n--- OS Version (sw_vers) ---")
            lines.append(out.strip() if out.strip() else f"(sw_vers failed: {err})")

            # uname -a
            out, rc, err = _run_cmd(["uname", "-a"], timeout=cmd_timeout)
            lines.append("\n--- Kernel (uname -a) ---")
            lines.append(out.strip() if out.strip() else f"(uname failed: {err})")

            # arch
            out, rc, err = _run_cmd(["uname", "-m"], timeout=cmd_timeout)
            lines.append(f"\nArchitecture: {out.strip() or '(unknown)'}")

            content = redact_content("\n".join(lines))
            artifacts.append(_make_artifact(
                "system_info.txt", content, "SUCCESS", "sw_vers+uname", t,
                redaction_applied=True,
            ))
        except Exception as exc:
            artifacts.append(_failed_artifact("system_info.txt", "sw_vers+uname", t, str(exc)))

        # ==================================================================
        # Artifact 2 — cpu.txt
        # sysctl machdep.cpu.brand_string, hw.ncpu, hw.physicalcpu
        # ==================================================================
        t = time.perf_counter()
        try:
            lines = []

            out, rc, err = _run_cmd(
                ["sysctl", "hw.ncpu", "hw.physicalcpu", "machdep.cpu.brand_string"],
                timeout=cmd_timeout,
            )
            lines.append("--- CPU Info (sysctl) ---")
            lines.append(out.strip() if out.strip() else f"(sysctl failed: {err})")

            # vm.loadavg gives raw load values (used in load.txt too)
            out, rc, err = _run_cmd(["sysctl", "-n", "vm.loadavg"], timeout=cmd_timeout)
            lines.append("\n--- Load Average (vm.loadavg) ---")
            lines.append(out.strip() if out.strip() else f"(failed: {err})")

            content = "\n".join(lines)
            artifacts.append(_make_artifact(
                "cpu.txt", content, "SUCCESS", "sysctl-cpu", t,
            ))
        except Exception as exc:
            artifacts.append(_failed_artifact("cpu.txt", "sysctl-cpu", t, str(exc)))

        # ==================================================================
        # Artifact 3 — memory.txt
        # vm_stat (macOS page statistics) + sysctl hw.memsize
        # ==================================================================
        t = time.perf_counter()
        try:
            lines = []

            # Physical RAM size
            out, rc, err = _run_cmd(["sysctl", "-n", "hw.memsize"], timeout=cmd_timeout)
            try:
                mem_bytes = int(out.strip())
                mem_gb = round(mem_bytes / (1024 ** 3), 2)
                lines.append(f"Physical Memory: {mem_gb} GB ({mem_bytes} bytes)")
            except Exception:
                lines.append(f"Physical Memory: (parse failed) {out.strip()}")

            # vm_stat page statistics
            out, rc, err = _run_cmd(["vm_stat"], timeout=cmd_timeout)
            lines.append("\n--- vm_stat ---")
            lines.append(out.strip() if out.strip() else f"(vm_stat failed: {err})")

            content = "\n".join(lines)
            artifacts.append(_make_artifact(
                "memory.txt", content, "SUCCESS", "vm_stat+sysctl", t,
            ))
        except Exception as exc:
            artifacts.append(_failed_artifact("memory.txt", "vm_stat+sysctl", t, str(exc)))

        # ==================================================================
        # Artifact 4 — disk.txt
        # df -h for each configured disk_path (bounded)
        # ==================================================================
        t = time.perf_counter()
        try:
            lines = []
            # Limit to at most 10 configured paths
            safe_paths = [p for p in disk_paths if isinstance(p, str)][:10]
            if not safe_paths:
                safe_paths = ["/"]

            for path in safe_paths:
                # Validate path is a simple absolute string (no shell injection)
                if not os.path.isabs(path):
                    lines.append(f"=== {path}: SKIPPED (not an absolute path) ===")
                    continue
                out, rc, err = _run_cmd(
                    ["df", "-h", path], timeout=cmd_timeout,
                )
                lines.append(f"=== df -h {path} ===")
                if out.strip():
                    lines.append(out.strip())
                else:
                    lines.append(f"(failed rc={rc}: {err})")

            content = "\n".join(lines)
            artifacts.append(_make_artifact(
                "disk.txt", content, "SUCCESS", "df-h", t,
            ))
        except Exception as exc:
            artifacts.append(_failed_artifact("disk.txt", "df-h", t, str(exc)))

        # ==================================================================
        # Artifact 5 — load.txt
        # uptime (includes load averages) + sysctl vm.loadavg
        # ==================================================================
        t = time.perf_counter()
        try:
            lines = []

            out, rc, err = _run_cmd(["uptime"], timeout=cmd_timeout)
            lines.append("--- uptime ---")
            lines.append(out.strip() if out.strip() else f"(uptime failed: {err})")

            out, rc, err = _run_cmd(["sysctl", "-n", "vm.loadavg"], timeout=cmd_timeout)
            lines.append("\n--- Load Average (vm.loadavg) ---")
            lines.append(out.strip() if out.strip() else f"(sysctl failed: {err})")

            content = "\n".join(lines)
            artifacts.append(_make_artifact(
                "load.txt", content, "SUCCESS", "uptime+sysctl", t,
            ))
        except Exception as exc:
            artifacts.append(_failed_artifact("load.txt", "uptime+sysctl", t, str(exc)))

        # ==================================================================
        # Artifact 6 — top_processes.txt
        # ps -ax sorted by %cpu descending, bounded rows, arguments redacted
        # ==================================================================
        t = time.perf_counter()
        try:
            # -r: sort by CPU (macOS ps supports -r)
            out, rc, err = _run_cmd(
                ["ps", "-ax", "-o", "pid,ppid,%cpu,%mem,command", "-r"],
                timeout=cmd_timeout,
            )
            if err == "TIMEOUT":
                artifacts.append(_failed_artifact(
                    "top_processes.txt", "ps-top", t, "ps timed out", "TIMEOUT",
                ))
            else:
                all_lines = out.splitlines()
                header = all_lines[0] if all_lines else "PID PPID %CPU %MEM COMMAND"
                # Filter out self, take top N
                data_lines = []
                for line in all_lines[1:]:
                    parts = line.strip().split(None, 4)
                    if not parts:
                        continue
                    try:
                        pid = int(parts[0])
                    except ValueError:
                        continue
                    if pid == self_pid:
                        continue
                    # Redact command field (index 4 if present)
                    if len(parts) == 5:
                        parts[4] = _redact_process_line(parts[4])
                    data_lines.append(" ".join(parts))

                kept = data_lines[:top_process_count]
                rows = [header] + kept
                if len(kept) == 0:
                    rows.append("(no processes captured)")
                content = redact_content("\n".join(rows))
                artifacts.append(_make_artifact(
                    "top_processes.txt", content, "SUCCESS", "ps-top", t,
                    exit_code=rc, redaction_applied=True,
                ))
        except Exception as exc:
            artifacts.append(_failed_artifact("top_processes.txt", "ps-top", t, str(exc)))

        # ==================================================================
        # Artifact 7 — network.txt
        # netstat -an -p tcp bounded to LISTEN lines only
        # ==================================================================
        t = time.perf_counter()
        try:
            # macOS: netstat -an -p tcp  (no --inet flag needed)
            out, rc, err = _run_cmd(
                ["netstat", "-an", "-p", "tcp"],
                timeout=cmd_timeout,
            )
            if err == "TIMEOUT":
                artifacts.append(_failed_artifact(
                    "network.txt", "netstat", t, "netstat timed out", "TIMEOUT",
                ))
            else:
                raw_lines = out.splitlines()
                # Keep only header lines and LISTEN entries
                kept = []
                for line in raw_lines:
                    upper = line.upper()
                    if upper.startswith("ACTIVE") or upper.startswith("PROTO") or "LISTEN" in upper:
                        kept.append(line)
                # Hard bound
                kept = kept[:_MAX_LINES]
                if not kept:
                    kept = ["(no LISTEN sockets detected or netstat returned no output)"]
                content = redact_content("\n".join(kept))
                artifacts.append(_make_artifact(
                    "network.txt", content, "SUCCESS", "netstat-listen", t,
                    exit_code=rc, redaction_applied=True,
                ))
        except Exception as exc:
            artifacts.append(_failed_artifact("network.txt", "netstat-listen", t, str(exc)))

        # ==================================================================
        # Artifact 8 — uptime.txt
        # Uptime details + boot time from sysctl kern.boottime
        # ==================================================================
        t = time.perf_counter()
        try:
            lines = []

            out, rc, err = _run_cmd(["uptime"], timeout=cmd_timeout)
            lines.append("--- uptime ---")
            lines.append(out.strip() if out.strip() else f"(uptime failed: {err})")

            out, rc, err = _run_cmd(["sysctl", "-n", "kern.boottime"], timeout=cmd_timeout)
            lines.append("\n--- Boot Time (kern.boottime) ---")
            lines.append(out.strip() if out.strip() else f"(sysctl failed: {err})")

            content = "\n".join(lines)
            artifacts.append(_make_artifact(
                "uptime.txt", content, "SUCCESS", "uptime+sysctl-boottime", t,
            ))
        except Exception as exc:
            artifacts.append(_failed_artifact("uptime.txt", "uptime+sysctl-boottime", t, str(exc)))

        # ------------------------------------------------------------------
        # Overall status
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

        return ProviderCaptureResult(
            provider_name=self.name,
            status=overall_status,
            artifacts=artifacts,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
        )


# ---------------------------------------------------------------------------
# Linux implementation
# Same artifact set — uses /proc-based commands and standard GNU tools.
# ---------------------------------------------------------------------------
class LinuxSystemSnapshotProvider(SystemSnapshotProvider):

    def capture(self, context: SnapshotContext) -> ProviderCaptureResult:
        started_at = datetime.now(timezone.utc)
        wall_start = time.perf_counter()

        provider_cfg = (
            context.config.get("snapshot", {})
            .get("providers", {})
            .get("system", {})
        )
        collectors_cfg = context.config.get("collectors", {}).get("system", {})

        cmd_timeout = float(
            provider_cfg.get("timeout")
            or collectors_cfg.get("timeout", 5.0)
        )
        disk_paths: List[str] = (
            provider_cfg.get("disk_paths")
            or [collectors_cfg.get("disk_path", "/")]
        )
        top_process_count = int(
            provider_cfg.get("top_process_count")
            or collectors_cfg.get("top_process_count", 15)
        )
        top_process_count = min(max(top_process_count, 1), 50)

        artifacts: List[CapturedArtifact] = []
        self_pid = os.getpid()

        # ------------------------------------------------------------------
        # Artifact 1 — system_info.txt
        # ------------------------------------------------------------------
        t = time.perf_counter()
        try:
            lines = []
            out, rc, err = _run_cmd(["hostname"], timeout=cmd_timeout)
            lines.append(f"Hostname: {out.strip() or '(unknown)'}")

            out, rc, err = _run_cmd(["uname", "-a"], timeout=cmd_timeout)
            lines.append("\n--- Kernel (uname -a) ---")
            lines.append(out.strip() if out.strip() else f"(uname failed: {err})")

            out, rc, err = _run_cmd(["uname", "-m"], timeout=cmd_timeout)
            lines.append(f"\nArchitecture: {out.strip() or '(unknown)'}")

            # /etc/os-release (Linux standard)
            try:
                with open("/etc/os-release", "r") as f:
                    osrel = f.read(2048)
                lines.append("\n--- /etc/os-release ---")
                lines.append(osrel.strip())
            except Exception:
                pass

            content = redact_content("\n".join(lines))
            artifacts.append(_make_artifact(
                "system_info.txt", content, "SUCCESS", "uname+os-release", t,
                redaction_applied=True,
            ))
        except Exception as exc:
            artifacts.append(_failed_artifact("system_info.txt", "uname+os-release", t, str(exc)))

        # ------------------------------------------------------------------
        # Artifact 2 — cpu.txt
        # ------------------------------------------------------------------
        t = time.perf_counter()
        try:
            lines = []
            # nproc for core count
            out, rc, err = _run_cmd(["nproc", "--all"], timeout=cmd_timeout)
            lines.append(f"Logical CPUs: {out.strip() or '(unknown)'}")

            # /proc/cpuinfo first 30 lines (bounded)
            try:
                with open("/proc/cpuinfo", "r") as f:
                    raw = f.read(8192)
                cpu_lines = raw.splitlines()[:30]
                lines.append("\n--- /proc/cpuinfo (first 30 lines) ---")
                lines.extend(cpu_lines)
            except Exception:
                pass

            content = "\n".join(lines)
            artifacts.append(_make_artifact(
                "cpu.txt", content, "SUCCESS", "nproc+cpuinfo", t,
            ))
        except Exception as exc:
            artifacts.append(_failed_artifact("cpu.txt", "nproc+cpuinfo", t, str(exc)))

        # ------------------------------------------------------------------
        # Artifact 3 — memory.txt
        # ------------------------------------------------------------------
        t = time.perf_counter()
        try:
            out, rc, err = _run_cmd(["free", "-h"], timeout=cmd_timeout)
            content = out.strip() if out.strip() else f"(free failed: {err})"
            artifacts.append(_make_artifact(
                "memory.txt", content, "SUCCESS", "free-h", t,
            ))
        except Exception as exc:
            artifacts.append(_failed_artifact("memory.txt", "free-h", t, str(exc)))

        # ------------------------------------------------------------------
        # Artifact 4 — disk.txt
        # ------------------------------------------------------------------
        t = time.perf_counter()
        try:
            lines = []
            safe_paths = [p for p in disk_paths if isinstance(p, str)][:10]
            if not safe_paths:
                safe_paths = ["/"]
            for path in safe_paths:
                if not os.path.isabs(path):
                    lines.append(f"=== {path}: SKIPPED (not absolute) ===")
                    continue
                out, rc, err = _run_cmd(["df", "-h", path], timeout=cmd_timeout)
                lines.append(f"=== df -h {path} ===")
                lines.append(out.strip() if out.strip() else f"(failed: {err})")
            content = "\n".join(lines)
            artifacts.append(_make_artifact(
                "disk.txt", content, "SUCCESS", "df-h", t,
            ))
        except Exception as exc:
            artifacts.append(_failed_artifact("disk.txt", "df-h", t, str(exc)))

        # ------------------------------------------------------------------
        # Artifact 5 — load.txt
        # ------------------------------------------------------------------
        t = time.perf_counter()
        try:
            lines = []
            out, rc, err = _run_cmd(["uptime"], timeout=cmd_timeout)
            lines.append("--- uptime ---")
            lines.append(out.strip() if out.strip() else f"(failed: {err})")

            try:
                with open("/proc/loadavg", "r") as f:
                    la = f.read(256).strip()
                lines.append(f"\n--- /proc/loadavg ---\n{la}")
            except Exception:
                pass

            content = "\n".join(lines)
            artifacts.append(_make_artifact(
                "load.txt", content, "SUCCESS", "uptime+loadavg", t,
            ))
        except Exception as exc:
            artifacts.append(_failed_artifact("load.txt", "uptime+loadavg", t, str(exc)))

        # ------------------------------------------------------------------
        # Artifact 6 — top_processes.txt
        # ------------------------------------------------------------------
        t = time.perf_counter()
        try:
            # GNU ps: -e all processes, -o fields, --sort=-%cpu
            out, rc, err = _run_cmd(
                ["ps", "-e", "-o", "pid,ppid,%cpu,%mem,comm", "--sort=-%cpu"],
                timeout=cmd_timeout,
            )
            if err == "TIMEOUT":
                artifacts.append(_failed_artifact(
                    "top_processes.txt", "ps-top", t, "ps timed out", "TIMEOUT",
                ))
            else:
                all_lines = out.splitlines()
                header = all_lines[0] if all_lines else "PID PPID %CPU %MEM COMMAND"
                data_lines = []
                for line in all_lines[1:]:
                    parts = line.strip().split(None, 4)
                    if not parts:
                        continue
                    try:
                        pid = int(parts[0])
                    except ValueError:
                        continue
                    if pid == self_pid:
                        continue
                    if len(parts) == 5:
                        parts[4] = _redact_process_line(parts[4])
                    data_lines.append(" ".join(parts))
                kept = data_lines[:top_process_count]
                rows = [header] + kept
                if not kept:
                    rows.append("(no processes captured)")
                content = redact_content("\n".join(rows))
                artifacts.append(_make_artifact(
                    "top_processes.txt", content, "SUCCESS", "ps-top", t,
                    exit_code=rc, redaction_applied=True,
                ))
        except Exception as exc:
            artifacts.append(_failed_artifact("top_processes.txt", "ps-top", t, str(exc)))

        # ------------------------------------------------------------------
        # Artifact 7 — network.txt
        # ------------------------------------------------------------------
        t = time.perf_counter()
        try:
            # ss is preferred on Linux; netstat is fallback
            out, rc, err = _run_cmd(
                ["ss", "-tlnp"],
                timeout=cmd_timeout,
            )
            if err == "TIMEOUT":
                artifacts.append(_failed_artifact(
                    "network.txt", "ss-listen", t, "ss timed out", "TIMEOUT",
                ))
            else:
                if not out.strip():
                    # fallback to netstat
                    out, rc, err = _run_cmd(
                        ["netstat", "-tlnp"],
                        timeout=cmd_timeout,
                    )
                raw_lines = out.splitlines()[:_MAX_LINES]
                if not raw_lines:
                    raw_lines = ["(no output)"]
                content = redact_content("\n".join(raw_lines))
                artifacts.append(_make_artifact(
                    "network.txt", content, "SUCCESS", "ss-listen", t,
                    exit_code=rc, redaction_applied=True,
                ))
        except Exception as exc:
            artifacts.append(_failed_artifact("network.txt", "ss-listen", t, str(exc)))

        # ------------------------------------------------------------------
        # Artifact 8 — uptime.txt
        # ------------------------------------------------------------------
        t = time.perf_counter()
        try:
            lines = []
            out, rc, err = _run_cmd(["uptime"], timeout=cmd_timeout)
            lines.append("--- uptime ---")
            lines.append(out.strip() if out.strip() else f"(failed: {err})")

            # /proc/uptime: seconds since boot
            try:
                with open("/proc/uptime", "r") as f:
                    raw = f.read(128).strip()
                seconds = float(raw.split()[0])
                days = int(seconds // 86400)
                hours = int((seconds % 86400) // 3600)
                minutes = int((seconds % 3600) // 60)
                lines.append(f"\n--- Boot time (from /proc/uptime) ---")
                lines.append(f"Up {days}d {hours}h {minutes}m")
            except Exception:
                pass

            content = "\n".join(lines)
            artifacts.append(_make_artifact(
                "uptime.txt", content, "SUCCESS", "uptime+proc-uptime", t,
            ))
        except Exception as exc:
            artifacts.append(_failed_artifact("uptime.txt", "uptime+proc-uptime", t, str(exc)))

        # ------------------------------------------------------------------
        # Overall status
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

        return ProviderCaptureResult(
            provider_name=self.name,
            status=overall_status,
            artifacts=artifacts,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
        )
