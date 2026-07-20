import os
import sys
import time
import socket
import subprocess
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import List, Optional
from app.snapshot.models import SnapshotContext, SnapshotProvider, CapturedArtifact, ProviderCaptureResult
from app.snapshot.redaction import redact_content
from app.snapshot.providers.utils import _tail_file


# ---------------------------------------------------------------------------
# Bounded metrics: only these Prometheus metric prefixes are retained.
# ---------------------------------------------------------------------------
_ALLOWED_METRIC_PREFIXES = (
    "cloudflared_tunnel_active_streams",
    "cloudflared_tunnel_ha_connections",
    "cloudflared_tunnel_request_errors",
    "cloudflared_tunnel_response_by_code",
    "process_open_fds",
    "process_virtual_memory_bytes",
)

# Maximum bytes read from a metrics endpoint response body.
_MAX_METRICS_BYTES = 32768  # 32 KB


def _token_match_process(command_field: str, signatures: List[str]) -> bool:
    """
    Returns True only when every signature term matches a whole command token
    (split on whitespace), not as an arbitrary substring.

    Example:
        command_field = "/usr/local/bin/cloudflared tunnel run mac-mini"
        signatures    = ["cloudflared"]
        → True   (token "cloudflared" found in basename of argv[0] and subsequent tokens)

    Example:
        command_field = "/opt/notacloudflared/helper"
        signatures    = ["cloudflared"]
        → False  (no token equals "cloudflared" exactly)

    The match strategy:
      - Split the full command string on whitespace to obtain argv tokens.
      - For each signature term, the match succeeds if the term equals:
          (a) any complete token, OR
          (b) the basename of the first token (argv[0]) — to handle paths like
              /usr/local/bin/cloudflared whose last path component is "cloudflared".
      - ALL signature terms must match (AND semantics).
    """
    if not command_field or not signatures:
        return False

    tokens = command_field.strip().split()
    if not tokens:
        return False

    # Build a set of matchable values: all tokens + basename of argv[0]
    argv0_basename = os.path.basename(tokens[0])
    matchable = set(tokens) | {argv0_basename}

    for term in signatures:
        if term not in matchable:
            return False
    return True


def _parse_bounded_metrics(raw: str) -> str:
    """
    Filters raw Prometheus text output, retaining only lines whose metric name
    starts with one of the allowed prefixes.  Comments (#) and empty lines for
    allowed metrics are preserved; everything else is dropped.
    """
    allowed_lines: List[str] = []
    current_metric_allowed = False

    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            # Include HELP/TYPE comments only for allowed metrics
            parts = stripped.split()
            # Format: # HELP metric_name ... or # TYPE metric_name ...
            if len(parts) >= 3 and any(parts[2].startswith(p) for p in _ALLOWED_METRIC_PREFIXES):
                current_metric_allowed = True
                allowed_lines.append(line)
            else:
                current_metric_allowed = False
        else:
            if any(stripped.startswith(p) for p in _ALLOWED_METRIC_PREFIXES):
                allowed_lines.append(line)
            # else: silently discard non-allowed metric lines

    return "\n".join(allowed_lines)


class CloudflaredSnapshotProvider(SnapshotProvider):
    @property
    def name(self) -> str:
        return "cloudflared"


class MacOSCloudflaredSnapshotProvider(CloudflaredSnapshotProvider):
    """
    Observer-only Cloudflare Tunnel forensic snapshot provider for macOS.

    Captures 6 independent artifacts:
      1. cloudflared_processes.txt  – OS process state
      2. tunnel_status.txt          – cloudflared tunnel info (best-effort)
      3. cloudflared.log            – bounded, redacted log tail
      4. dns_resolution.txt         – DNS resolution for configured public hostnames
      5. local_origin.txt           – local origin reachability (HTTP HEAD)
      6. metrics.txt                – bounded Prometheus metrics (opt-in)

    NEVER modifies cloudflared, DNS, config files, or credentials.
    """

    def capture(self, context: SnapshotContext) -> ProviderCaptureResult:
        started_at = datetime.now(timezone.utc)
        start_time = time.perf_counter()

        # ------------------------------------------------------------------
        # Configuration resolution: snapshot.providers.cloudflared overrides
        # collectors.cloudflared, which provides the fallback.
        # ------------------------------------------------------------------
        provider_config = (
            context.config.get("snapshot", {})
            .get("providers", {})
            .get("cloudflared", {})
        )
        collectors_cf = context.config.get("collectors", {}).get("cloudflared", {})

        tunnel_name      = provider_config.get("tunnel_name")    or collectors_cf.get("tunnel_name", "")
        log_path         = provider_config.get("log_path")       or collectors_cf.get("log_path", "")
        config_path      = provider_config.get("config_path")    or collectors_cf.get("config_path", "")  # kept for reference; never opened
        max_lines        = provider_config.get("max_lines",       collectors_cf.get("log_lines", 500))
        max_bytes        = provider_config.get("max_bytes",       1048576)
        process_sig      = provider_config.get("process_signature", ["cloudflared"])
        status_timeout   = float(provider_config.get("status_timeout", 5.0))
        public_hostnames = provider_config.get("public_hostnames", [])
        local_origin_url = provider_config.get("local_origin_url", "")
        metrics_url      = provider_config.get("metrics_url", "")

        artifacts: List[CapturedArtifact] = []

        # ==================================================================
        # Artifact 1 — cloudflared_processes.txt
        # ==================================================================
        ps_start = time.perf_counter()
        try:
            ps_cmd = ["ps", "-ax", "-o", "pid,ppid,%cpu,%mem,command"]
            res = subprocess.run(ps_cmd, capture_output=True, text=True, shell=False, timeout=1.0)
            self_pid = os.getpid()
            lines = res.stdout.splitlines()
            header = lines[0] if lines else "PID PPID %CPU %MEM COMMAND"

            filtered: List[str] = [header]
            for line in lines[1:]:
                # Columns: PID PPID %CPU %MEM COMMAND…
                # COMMAND starts at index 4 when split by whitespace.
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
                if _token_match_process(command_field, process_sig):
                    filtered.append(line)

            if len(filtered) == 1:
                # Header only — process absent is a valid forensic observation
                filtered.append("cloudflared: No matching processes found at snapshot time.")

            content = redact_content("\n".join(filtered))
            ps_duration = round((time.perf_counter() - ps_start) * 1000, 2)
            artifacts.append(CapturedArtifact(
                name="cloudflared_processes.txt",
                content=content,
                status="SUCCESS",
                capture_method="ps-token-filter",
                captured_at=datetime.now(timezone.utc),
                duration_ms=ps_duration,
                exit_code=res.returncode,
                bytes_captured=len(content.encode("utf-8")),
                lines_captured=len(content.splitlines()),
            ))
        except subprocess.TimeoutExpired:
            ps_duration = round((time.perf_counter() - ps_start) * 1000, 2)
            artifacts.append(CapturedArtifact(
                name="cloudflared_processes.txt",
                content="",
                status="TIMEOUT",
                capture_method="ps-token-filter",
                captured_at=datetime.now(timezone.utc),
                duration_ms=ps_duration,
                error_message="ps command timed out",
            ))
        except Exception as e:
            ps_duration = round((time.perf_counter() - ps_start) * 1000, 2)
            artifacts.append(CapturedArtifact(
                name="cloudflared_processes.txt",
                content="",
                status="FAILED",
                capture_method="ps-token-filter",
                captured_at=datetime.now(timezone.utc),
                duration_ms=ps_duration,
                error_message=str(e),
            ))

        # ==================================================================
        # Artifact 2 — tunnel_status.txt
        # Best-effort: all non-timeout/non-exception outcomes are SUCCESS
        # (including non-zero exit codes such as auth errors or "not found").
        # ==================================================================
        ts_start = time.perf_counter()
        try:
            if not tunnel_name:
                ts_content = "Tunnel name not configured — status inspection skipped."
                ts_status  = "SUCCESS"
                ts_method  = "skipped"
                ts_exit    = None
            else:
                cmd = ["cloudflared", "tunnel", "info", tunnel_name]
                res = subprocess.run(
                    cmd, capture_output=True, text=True, shell=False, timeout=status_timeout
                )
                raw_output = (res.stdout + res.stderr).strip()
                if raw_output:
                    ts_content = redact_content(raw_output)
                else:
                    ts_content = "Tunnel status: No output returned by cloudflared tunnel info."
                ts_status  = "SUCCESS"   # forensic observation regardless of exit code
                ts_method  = "cloudflared-tunnel-info"
                ts_exit    = res.returncode

            ts_duration = round((time.perf_counter() - ts_start) * 1000, 2)
            artifacts.append(CapturedArtifact(
                name="tunnel_status.txt",
                content=ts_content,
                status=ts_status,
                capture_method=ts_method,
                captured_at=datetime.now(timezone.utc),
                duration_ms=ts_duration,
                exit_code=ts_exit,
                bytes_captured=len(ts_content.encode("utf-8")),
                lines_captured=len(ts_content.splitlines()),
            ))
        except FileNotFoundError:
            # cloudflared binary absent from PATH — forensic observation
            ts_duration = round((time.perf_counter() - ts_start) * 1000, 2)
            content = "cloudflared binary not found in PATH — status inspection skipped."
            artifacts.append(CapturedArtifact(
                name="tunnel_status.txt",
                content=content,
                status="SUCCESS",
                capture_method="cloudflared-tunnel-info",
                captured_at=datetime.now(timezone.utc),
                duration_ms=ts_duration,
                bytes_captured=len(content.encode("utf-8")),
                lines_captured=1,
            ))
        except subprocess.TimeoutExpired:
            ts_duration = round((time.perf_counter() - ts_start) * 1000, 2)
            artifacts.append(CapturedArtifact(
                name="tunnel_status.txt",
                content="",
                status="TIMEOUT",
                capture_method="cloudflared-tunnel-info",
                captured_at=datetime.now(timezone.utc),
                duration_ms=ts_duration,
                error_message=f"cloudflared tunnel info timed out after {status_timeout}s",
            ))
        except Exception as e:
            ts_duration = round((time.perf_counter() - ts_start) * 1000, 2)
            artifacts.append(CapturedArtifact(
                name="tunnel_status.txt",
                content="",
                status="FAILED",
                capture_method="cloudflared-tunnel-info",
                captured_at=datetime.now(timezone.utc),
                duration_ms=ts_duration,
                error_message=str(e),
            ))

        # ==================================================================
        # Artifact 3 — cloudflared.log
        # ==================================================================
        log_start = time.perf_counter()
        try:
            content, truncated, lines_read, bytes_read = _tail_file(log_path, max_lines, max_bytes)
            if content == "" and os.path.exists(log_path):
                content = "Log file existed but was empty at snapshot time."
                bytes_read = len(content.encode("utf-8"))
                lines_read = 1
            try:
                sanitized = redact_content(content)
            except Exception as re_err:
                raise RuntimeError(f"Redaction failed: {re_err}")

            log_duration = round((time.perf_counter() - log_start) * 1000, 2)
            artifacts.append(CapturedArtifact(
                name="cloudflared.log",
                content=sanitized,
                status="SUCCESS",
                capture_method="file-tail",
                captured_at=datetime.now(timezone.utc),
                duration_ms=log_duration,
                truncated=truncated,
                bytes_captured=bytes_read,
                lines_captured=lines_read,
                redaction_applied=True,
            ))
        except Exception as e:
            log_duration = round((time.perf_counter() - log_start) * 1000, 2)
            artifacts.append(CapturedArtifact(
                name="cloudflared.log",
                content="",
                status="FAILED",
                capture_method="file-tail",
                captured_at=datetime.now(timezone.utc),
                duration_ms=log_duration,
                error_message=str(e),
            ))

        # ==================================================================
        # Artifact 4 — dns_resolution.txt
        #
        # Status semantics (per correction 2):
        #   SUCCESS  → command ran AND returned any result (resolved or NXDOMAIN)
        #   TIMEOUT  → command exceeded timeout
        #   FAILED   → internal tool failure (binary missing, unexpected exception)
        #
        # A NXDOMAIN response is forensic evidence of DNS failure, not a
        # snapshot-provider failure. All per-hostname results are preserved.
        # ==================================================================
        dns_start = time.perf_counter()
        if not public_hostnames:
            dns_content = "DNS resolution skipped: no public_hostnames configured."
            dns_status  = "SUCCESS"
            dns_method  = "skipped"
        else:
            dns_lines:  List[str] = []
            any_success = False
            any_timeout = False
            any_failed  = False

            for hostname in public_hostnames:
                h_result, h_outcome = _resolve_hostname(hostname, timeout=3.0)
                dns_lines.append(f"=== DNS: {hostname} ===")
                dns_lines.append(h_result)
                if h_outcome == "success":
                    any_success = True
                elif h_outcome == "timeout":
                    any_timeout = True
                else:  # "failed"
                    any_failed = True

            dns_content = "\n".join(dns_lines)
            dns_content = redact_content(dns_content)

            # Artifact-level status: FAILED only when the DNS tool itself cannot run.
            # NXDOMAIN outcomes count as "success" (forensic observation).
            if any_failed and not any_success and not any_timeout:
                dns_status = "FAILED"
            elif any_timeout and not any_success:
                dns_status = "TIMEOUT"
            else:
                dns_status = "SUCCESS"
            dns_method = "host-lookup"

        dns_duration = round((time.perf_counter() - dns_start) * 1000, 2)
        artifacts.append(CapturedArtifact(
            name="dns_resolution.txt",
            content=dns_content,
            status=dns_status,
            capture_method=dns_method,
            captured_at=datetime.now(timezone.utc),
            duration_ms=dns_duration,
            bytes_captured=len(dns_content.encode("utf-8")),
            lines_captured=len(dns_content.splitlines()),
        ))

        # ==================================================================
        # Artifact 5 — local_origin.txt
        # HTTP HEAD against the configured local origin URL.
        # Only HTTP status code is captured — response body is never read.
        # ==================================================================
        lo_start = time.perf_counter()
        if not local_origin_url:
            lo_content = "Local origin check skipped: no local_origin_url configured."
            lo_status  = "SUCCESS"
            lo_method  = "skipped"
        else:
            lo_content, lo_status = _check_local_origin(local_origin_url, timeout=status_timeout)
            lo_content = redact_content(lo_content)
            lo_method  = "http-head"

        lo_duration = round((time.perf_counter() - lo_start) * 1000, 2)
        artifacts.append(CapturedArtifact(
            name="local_origin.txt",
            content=lo_content,
            status=lo_status,
            capture_method=lo_method,
            captured_at=datetime.now(timezone.utc),
            duration_ms=lo_duration,
            bytes_captured=len(lo_content.encode("utf-8")),
            lines_captured=len(lo_content.splitlines()),
        ))

        # ==================================================================
        # Artifact 6 — metrics.txt  (opt-in, bounded)
        # Only executed when metrics_url is explicitly configured.
        # ==================================================================
        m_start = time.perf_counter()
        if not metrics_url:
            m_content = "Metrics endpoint not configured — metrics capture skipped."
            m_status  = "SUCCESS"
            m_method  = "skipped"
        else:
            m_content, m_status = _fetch_metrics(metrics_url, timeout=status_timeout)
            m_content = redact_content(m_content)
            m_method  = "http-get-metrics"

        m_duration = round((time.perf_counter() - m_start) * 1000, 2)
        artifacts.append(CapturedArtifact(
            name="metrics.txt",
            content=m_content,
            status=m_status,
            capture_method=m_method,
            captured_at=datetime.now(timezone.utc),
            duration_ms=m_duration,
            bytes_captured=len(m_content.encode("utf-8")),
            lines_captured=len(m_content.splitlines()),
        ))

        # ------------------------------------------------------------------
        # Overall provider status
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
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

        return ProviderCaptureResult(
            provider_name=self.name,
            status=overall_status,
            artifacts=artifacts,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
        )


# ---------------------------------------------------------------------------
# Module-level helpers (pure functions, easily unit-tested)
# ---------------------------------------------------------------------------

def _resolve_hostname(hostname: str, timeout: float) -> tuple:
    """
    Resolves a single hostname using `host` (or `nslookup` as fallback).
    Returns (output_text: str, outcome: Literal["success", "timeout", "failed"]).

    Outcome semantics:
      "success" — the DNS tool ran and returned output (resolved OR NXDOMAIN).
      "timeout" — the subprocess exceeded `timeout` seconds.
      "failed"  — the DNS tool binary was not found or raised an unexpected error.
    """
    for dns_tool, args in [
        ("host",     ["host",     hostname]),
        ("nslookup", ["nslookup", hostname]),
    ]:
        try:
            res = subprocess.run(
                args, capture_output=True, text=True, shell=False, timeout=timeout
            )
            output = (res.stdout + res.stderr).strip()
            # Non-zero exit (NXDOMAIN, not found) is still a valid forensic result.
            return (
                f"{' '.join(args)}\n{output}" if output else f"{' '.join(args)}\n(no output)",
                "success",
            )
        except FileNotFoundError:
            # Try next tool
            continue
        except subprocess.TimeoutExpired:
            return (f"TIMEOUT after {timeout}s", "timeout")
        except Exception as e:
            return (f"FAILED: {e}", "failed")

    # Both tools unavailable
    return ("DNS tool not available (host, nslookup both missing)", "failed")


def _check_local_origin(url: str, timeout: float) -> tuple:
    """
    Issues a HEAD request (falling back to GET) to `url` within `timeout` seconds.
    Only the HTTP status code is captured — the response body is never read.

    Returns (content: str, status: Literal["SUCCESS", "TIMEOUT", "FAILED"]).
    """
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            http_status = resp.status
        content = (
            f"Local Origin: {url}\n"
            f"HTTP Status: {http_status}\n"
            f"Reachable: true\n"
        )
        return content, "SUCCESS"
    except urllib.error.HTTPError as e:
        # HTTP error response (4xx/5xx) — service reachable but returned an error
        content = (
            f"Local Origin: {url}\n"
            f"HTTP Status: {e.code}\n"
            f"Reachable: false\n"
            f"Reason: HTTP {e.code} {e.reason}\n"
        )
        return content, "SUCCESS"
    except urllib.error.URLError as e:
        reason = str(e.reason) if hasattr(e, "reason") else str(e)
        content = (
            f"Local Origin: {url}\n"
            f"Reachable: false\n"
            f"Reason: {reason}\n"
        )
        return content, "SUCCESS"
    except (socket.timeout, TimeoutError):
        return ("", "TIMEOUT")
    except Exception as e:
        return ("", "FAILED")


def _fetch_metrics(metrics_url: str, timeout: float) -> tuple:
    """
    Fetches Prometheus-format metrics from `metrics_url`, bounded to
    _MAX_METRICS_BYTES. Returns only lines matching _ALLOWED_METRIC_PREFIXES.

    Returns (content: str, status: Literal["SUCCESS", "TIMEOUT", "FAILED"]).
    """
    try:
        req = urllib.request.Request(metrics_url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                content = f"Metrics endpoint unavailable (HTTP {resp.status})"
                return content, "SUCCESS"
            raw_bytes = resp.read(_MAX_METRICS_BYTES)
        raw_text = raw_bytes.decode("utf-8", errors="ignore")
        filtered = _parse_bounded_metrics(raw_text)
        content = filtered if filtered.strip() else "Metrics available but no matching metric names found."
        return content, "SUCCESS"
    except urllib.error.HTTPError as e:
        content = f"Metrics endpoint unavailable (HTTP {e.code} {e.reason})"
        return content, "SUCCESS"
    except urllib.error.URLError as e:
        reason = str(e.reason) if hasattr(e, "reason") else str(e)
        content = f"Metrics endpoint not reachable: {reason}"
        return content, "SUCCESS"
    except (socket.timeout, TimeoutError):
        return ("", "TIMEOUT")
    except Exception as e:
        return ("", "FAILED")


class LinuxCloudflaredSnapshotProvider(CloudflaredSnapshotProvider):
    """Stub implementation for future Linux deployments."""
    def capture(self, context: SnapshotContext) -> ProviderCaptureResult:
        started_at = datetime.now(timezone.utc)
        return ProviderCaptureResult(
            provider_name=self.name,
            status="FAILED",
            artifacts=[],
            started_at=started_at,
            finished_at=started_at,
            duration_ms=0.0,
            error_message="Linux Cloudflared provider not implemented in this batch",
        )
