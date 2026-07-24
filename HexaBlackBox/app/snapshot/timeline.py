import os
import re
import json
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger("TimelineGenerator")

# ---------------------------------------------------------------------------
# Bounded Constants
# ---------------------------------------------------------------------------
MAX_BYTES_PER_ARTIFACT = 128 * 1024  # 128 KB
MAX_LINES_PER_ARTIFACT = 100
MAX_TIMELINE_EVENTS = 250

# ---------------------------------------------------------------------------
# Timestamp Parsers
# ---------------------------------------------------------------------------

def parse_iso_utc(ts_str: str) -> Optional[datetime]:
    """Parse ISO 8601 UTC timestamp string (e.g. 2026-07-24T11:30:00Z or +00:00)."""
    if not ts_str:
        return None
    try:
        clean_str = ts_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean_str)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None

def parse_incident_started_at(ts_str: str) -> Optional[datetime]:
    """Parse local incident started_at string 'YYYY-MM-DD HH:MM:SS' as UTC fallback."""
    if not ts_str:
        return None
    try:
        dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        return dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None

def parse_nginx_access_time(time_str: str) -> Optional[datetime]:
    """Parse Nginx Common Log Format timestamp: 24/Jul/2026:11:30:00 +0000"""
    try:
        # Strip brackets if present
        clean = time_str.strip("[]")
        dt = datetime.strptime(clean, "%d/%b/%Y:%H:%M:%S %z")
        return dt.astimezone(timezone.utc)
    except Exception:
        return None

def parse_nginx_error_time(time_str: str) -> Optional[datetime]:
    """Parse Nginx error log timestamp: 2026/07/24 11:30:00"""
    try:
        dt = datetime.strptime(time_str, "%Y/%m/%d %H:%M:%S")
        return dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None

def parse_backend_log_time(line: str) -> Optional[datetime]:
    """
    Extract timestamp from Uvicorn / Python backend log line.
    Matches formats like:
      - 2026-07-24 11:30:00.123 [INFO] ...
      - 2026-07-24T11:30:00Z INFO: ...
    Returns datetime in UTC or None.
    """
    pattern = r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)"
    match = re.search(pattern, line)
    if not match:
        return None
    
    ts_match = match.group(1)
    if "T" in ts_match or "Z" in ts_match or "+" in ts_match:
        dt = parse_iso_utc(ts_match)
        if dt:
            return dt

    # Fallback for "2026-07-24 11:30:00" or "2026-07-24 11:30:00.123"
    try:
        clean = ts_match.split(".")[0]
        dt = datetime.strptime(clean, "%Y-%m-%d %H:%M:%S")
        return dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None

# ---------------------------------------------------------------------------
# Timeline Generator Engine
# ---------------------------------------------------------------------------

class TimelineGenerator:
    """
    Synthesizes a unified incident timeline from:
    1. First-class incident trigger metadata (INCIDENT_TRIGGERED / FAILURE_CONFIRMED)
    2. Provider execution lifecycle & metadata.json sidecars
    3. Differential HTTP probe observations (probe_ping, probe_health)
    4. Bounded log parsing (Nginx access/error logs, Backend stdout/stderr)
    """

    @classmethod
    def build_timeline(cls, evidence_dir: str, manifest: dict, incident_payload: Optional[dict] = None) -> Tuple[dict, str]:
        """
        Builds normalized timeline events, enforces strict ordering, applies bounded caps,
        and returns both (timeline_dict, timeline_text_summary).
        """
        events: List[Dict[str, Any]] = []

        # 1. First-class Incident Trigger Event
        cls._extract_incident_trigger_event(events, manifest, incident_payload)

        # 2. Extract Provider Lifecycle Events & Probe Artifact Observations
        cls._extract_provider_and_probe_events(events, evidence_dir, manifest)

        # 3. Extract Log Events (Nginx & Backend) with Strict Timestamp Parsing
        cls._extract_log_events(events, evidence_dir)

        # 4. Sort Events Chronologically
        # Events with reliably parsed event timestamps are sorted chronologically.
        # Events where timestamp could not be parsed are placed at the end with timestamp_known=false.
        events_with_time = [e for e in events if e.get("timestamp_known", True) and e.get("timestamp")]
        events_without_time = [e for e in events if not e.get("timestamp_known", True) or not e.get("timestamp")]

        events_with_time.sort(key=lambda x: x["timestamp"])

        # Enforce MAX_TIMELINE_EVENTS bounded cap
        combined_events = events_with_time + events_without_time
        if len(combined_events) > MAX_TIMELINE_EVENTS:
            combined_events = combined_events[:MAX_TIMELINE_EVENTS]

        incident_id = manifest.get("incident_id", "UNKNOWN_INCIDENT")
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        timeline_dict = {
            "timeline_schema_version": 1,
            "incident_id": incident_id,
            "generated_at": generated_at,
            "total_events": len(combined_events),
            "events": combined_events
        }

        timeline_text = cls._format_text_timeline(incident_id, generated_at, combined_events)
        return timeline_dict, timeline_text

    @classmethod
    def _extract_incident_trigger_event(cls, events: List[Dict[str, Any]], manifest: dict, incident_payload: Optional[dict]):
        """Creates authoritative INCIDENT_TRIGGERED first-class timeline event."""
        incident_id = manifest.get("incident_id", "UNKNOWN")
        
        # Check incident payload first for started_at
        started_at_str = None
        target_name = "Target"
        failure_reason = "Health check failure"
        
        if incident_payload:
            started_at_str = incident_payload.get("started_at")
            target_name = incident_payload.get("target_name", target_name)
            failure_reason = incident_payload.get("failure_reason", failure_reason)
            
        dt = parse_incident_started_at(started_at_str) if started_at_str else None
        
        if dt:
            ts_iso = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            timestamp_known = True
        else:
            ts_iso = None
            timestamp_known = False

        events.append({
            "timestamp": ts_iso,
            "timestamp_known": timestamp_known,
            "source_provider": "monitor",
            "artifact_name": "incident.json",
            "event_type": "INCIDENT_TRIGGERED",
            "severity": "CRITICAL",
            "summary": f"Incident {incident_id} triggered for target '{target_name}': {failure_reason}",
            "details": {
                "target_name": target_name,
                "failure_reason": failure_reason,
                "raw_started_at": started_at_str
            }
        })

    @classmethod
    def _extract_provider_and_probe_events(cls, events: List[Dict[str, Any]], evidence_dir: str, manifest: dict):
        """Extracts provider execution status and probe observation events from metadata.json sidecars."""
        results = manifest.get("results", [])
        
        for res in results:
            p_name = res.get("provider_name")
            p_dir = os.path.join(evidence_dir, p_name)
            meta_path = os.path.join(p_dir, "metadata.json")
            
            if not os.path.isfile(meta_path):
                continue
                
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception:
                continue

            provider_captured_at = meta.get("captured_at")
            provider_status = meta.get("status", "UNKNOWN")
            
            # Provider summary event
            events.append({
                "timestamp": provider_captured_at,
                "timestamp_known": bool(provider_captured_at),
                "source_provider": p_name,
                "artifact_name": "metadata.json",
                "event_type": "PROVIDER_SNAPSHOT",
                "severity": "INFO" if provider_status == "SUCCESS" else ("WARNING" if provider_status == "PARTIAL" else "ERROR"),
                "summary": f"Provider '{p_name}' snapshot completed with status {provider_status}",
                "details": {
                    "duration_ms": meta.get("duration_ms"),
                    "bytes_written": meta.get("bytes_written"),
                    "status": provider_status
                }
            })
            
            # Extract HTTP Probes from backend provider
            artifacts = meta.get("artifacts", [])
            for art in artifacts:
                art_name = art.get("name", "")
                if art_name in ("probe_ping.txt", "probe_health.txt"):
                    cls._extract_probe_artifact_event(events, p_dir, art_name, art)

    @classmethod
    def _extract_probe_artifact_event(cls, events: List[Dict[str, Any]], p_dir: str, art_name: str, art_meta: dict):
        """Parses probe content body to create high-value probe observation timeline events."""
        art_path = os.path.join(p_dir, art_name)
        if not os.path.isfile(art_path):
            return
            
        try:
            with open(art_path, "r", encoding="utf-8") as f:
                content = f.read(2048)
        except Exception:
            return

        probe_result = "UNKNOWN"
        http_status = None
        url = None
        
        for line in content.splitlines():
            if line.startswith("probe_result:"):
                probe_result = line.split(":", 1)[1].strip()
            elif line.startswith("http_status:"):
                try:
                    http_status = int(line.split(":", 1)[1].strip())
                except ValueError:
                    pass
            elif line.startswith("url:"):
                url = line.split(":", 1)[1].strip()

        severity = "INFO" if probe_result == "OK" else "CRITICAL"
        captured_at = art_meta.get("captured_at")
        
        events.append({
            "timestamp": captured_at,
            "timestamp_known": bool(captured_at),
            "source_provider": "backend",
            "artifact_name": art_name,
            "event_type": "PROBE_OBSERVATION",
            "severity": severity,
            "summary": f"Probe {art_name} result: {probe_result}" + (f" (HTTP {http_status})" if http_status else ""),
            "details": {
                "url": url,
                "probe_result": probe_result,
                "http_status": http_status,
                "capture_time": captured_at
            }
        })

    @classmethod
    def _extract_log_events(cls, events: List[Dict[str, Any]], evidence_dir: str):
        """Scans log artifacts for Nginx and Backend to parse exact timestamps."""
        # 1. Nginx error.log
        nginx_error_path = os.path.join(evidence_dir, "nginx", "error.log")
        cls._parse_nginx_error_log(events, nginx_error_path)

        # 2. Nginx access.log
        nginx_access_path = os.path.join(evidence_dir, "nginx", "access.log")
        cls._parse_nginx_access_log(events, nginx_access_path)

        # 3. Backend stdout.log / stderr.log
        for log_name in ("stdout.log", "stderr.log"):
            backend_log_path = os.path.join(evidence_dir, "backend", log_name)
            cls._parse_backend_log(events, backend_log_path, log_name)

    @classmethod
    def _read_bounded_lines(cls, file_path: str) -> List[str]:
        """Reads at most MAX_BYTES_PER_ARTIFACT and returns at most MAX_LINES_PER_ARTIFACT lines."""
        if not os.path.isfile(file_path):
            return []
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read(MAX_BYTES_PER_ARTIFACT)
            lines = content.splitlines()
            return lines[-MAX_LINES_PER_ARTIFACT:]
        except Exception:
            return []

    @classmethod
    def _parse_nginx_error_log(cls, events: List[Dict[str, Any]], file_path: str):
        lines = cls._read_bounded_lines(file_path)
        for line in lines:
            if not line.strip() or "Log file existed but was empty" in line:
                continue
            # Nginx error log timestamp format: 2026/07/24 11:30:00 [error] ...
            match = re.match(r"^(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}) \[(error|crit|warn|alert|emerg)\] (.*)", line)
            if match:
                raw_time, level, msg = match.groups()
                dt = parse_nginx_error_time(raw_time)
                ts_iso = dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None
                
                # High-value upstream / 502 diagnostics
                is_critical = any(kw in msg.lower() for kw in ("upstream", "connection refused", "connect() failed", "502", "no live upstreams"))
                
                events.append({
                    "timestamp": ts_iso,
                    "timestamp_known": dt is not None,
                    "source_provider": "nginx",
                    "artifact_name": "error.log",
                    "event_type": "NGINX_ERROR",
                    "severity": "CRITICAL" if is_critical else level.upper(),
                    "summary": f"[nginx error] {msg[:120]}",
                    "details": {"raw_line": line}
                })

    @classmethod
    def _parse_nginx_access_log(cls, events: List[Dict[str, Any]], file_path: str):
        lines = cls._read_bounded_lines(file_path)
        for line in lines:
            if not line.strip() or "Log file existed but was empty" in line:
                continue
            # Look for 5xx errors in access log
            # Typical format: 127.0.0.1 - - [24/Jul/2026:11:30:00 +0000] "GET /api HTTP/1.1" 502 ...
            time_match = re.search(r"\[(\d{2}/[A-Za-z]{3}/\d{4}:\d{2}:\d{2}:\d{2} \+\d{4})\]", line)
            status_match = re.search(r'"\s+(5\d{2})\s+', line)
            
            if status_match:
                status_code = status_match.group(1)
                dt = parse_nginx_access_time(time_match.group(1)) if time_match else None
                ts_iso = dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None
                
                events.append({
                    "timestamp": ts_iso,
                    "timestamp_known": dt is not None,
                    "source_provider": "nginx",
                    "artifact_name": "access.log",
                    "event_type": "NGINX_ACCESS_5XX",
                    "severity": "CRITICAL" if status_code == "502" else "ERROR",
                    "summary": f"[nginx access] HTTP {status_code} response returned to client",
                    "details": {"status_code": status_code, "raw_line": line}
                })

    @classmethod
    def _parse_backend_log(cls, events: List[Dict[str, Any]], file_path: str, artifact_name: str):
        lines = cls._read_bounded_lines(file_path)
        for line in lines:
            if not line.strip() or "Log file existed but was empty" in line:
                continue
            
            # Check for error/warning indicators
            line_lower = line.lower()
            if any(kw in line_lower for kw in ("error", "exception", "traceback", "critical", "failed", "refused")):
                dt = parse_backend_log_time(line)
                ts_iso = dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None
                
                events.append({
                    "timestamp": ts_iso,
                    "timestamp_known": dt is not None,
                    "source_provider": "backend",
                    "artifact_name": artifact_name,
                    "event_type": "BACKEND_LOG_ERROR",
                    "severity": "ERROR",
                    "summary": f"[backend {artifact_name}] {line[:120]}",
                    "details": {"raw_line": line}
                })

    @classmethod
    def _format_text_timeline(cls, incident_id: str, generated_at: str, events: List[Dict[str, Any]]) -> str:
        header = (
            f"================================================================================\n"
            f"UNIFIED INCIDENT TIMELINE — {incident_id}\n"
            f"Generated At: {generated_at} | Total Events: {len(events)}\n"
            f"================================================================================\n"
        )
        body_lines = []
        for e in events:
            ts_str = e["timestamp"] if e.get("timestamp_known", True) and e.get("timestamp") else "TIMESTAMP_UNKNOWN"
            src = f"{e['source_provider']}/{e['artifact_name']}"
            sev = e["severity"]
            ev_type = e.get("event_type", "EVENT")
            summary = e["summary"]
            body_lines.append(f"[{ts_str}] [{src}] [{sev}] [{ev_type}] {summary}")

        footer = "\n================================================================================\n"
        return header + "\n".join(body_lines) + footer
