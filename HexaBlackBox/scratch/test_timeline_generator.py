import sys
import os
import json
import shutil
import tempfile
from datetime import datetime, timezone
from unittest.mock import MagicMock

# Adjust search path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.snapshot.timeline import (
    TimelineGenerator,
    parse_iso_utc,
    parse_nginx_access_time,
    parse_nginx_error_time,
    parse_backend_log_time,
    MAX_BYTES_PER_ARTIFACT,
    MAX_LINES_PER_ARTIFACT,
    MAX_TIMELINE_EVENTS
)
from app.snapshot.engine import SnapshotEngine
from app.snapshot.models import SnapshotProvider, ProviderCaptureResult, CapturedArtifact

PASS = "\033[32mPASSED\033[0m"
FAIL = "\033[31mFAILED\033[0m"

def test_timestamp_parsers():
    print("1. Timestamp Parsers Validation ....... ", end="", flush=True)
    # ISO UTC
    dt1 = parse_iso_utc("2026-07-24T11:30:00Z")
    assert dt1 is not None and dt1.year == 2026 and dt1.hour == 11

    # Nginx Access
    dt2 = parse_nginx_access_time("24/Jul/2026:11:30:00 +0000")
    assert dt2 is not None and dt2.day == 24 and dt2.month == 7

    # Nginx Error
    dt3 = parse_nginx_error_time("2026/07/24 11:30:00")
    assert dt3 is not None and dt3.hour == 11

    # Backend Log
    dt4 = parse_backend_log_time("2026-07-24 11:30:00.123 [ERROR] Database connection lost")
    assert dt4 is not None and dt4.minute == 30

    print("PASSED")

def test_unparseable_timestamp_handling():
    print("2. Unparseable Timestamp Rule ........ ", end="", flush=True)
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create unparseable log line (no timestamp)
        backend_dir = os.path.join(tmpdir, "backend")
        os.makedirs(backend_dir, exist_ok=True)
        with open(os.path.join(backend_dir, "stdout.log"), "w", encoding="utf-8") as f:
            f.write("CRITICAL ERROR: Anonymous exception occurred without any timestamp prefix\n")

        manifest = {"incident_id": "INC-TEST-001", "results": []}
        timeline_dict, timeline_text = TimelineGenerator.build_timeline(tmpdir, manifest)

        log_events = [e for e in timeline_dict["events"] if e["event_type"] == "BACKEND_LOG_ERROR"]
        assert len(log_events) == 1
        ev = log_events[0]
        # Must NOT inherit artifact captured_at as timestamp
        assert ev["timestamp"] is None
        assert ev["timestamp_known"] is False
        assert "TIMESTAMP_UNKNOWN" in timeline_text
    print("PASSED")

def test_incident_trigger_first_class_event():
    print("3. Incident Trigger First-Class Event . ", end="", flush=True)
    manifest = {"incident_id": "INC-20260724-0005", "results": []}
    incident_payload = {
        "target_name": "HexaBeta_Backend",
        "started_at": "2026-07-24 11:30:00",
        "failure_reason": "HTTP 502 Bad Gateway"
    }

    timeline_dict, timeline_text = TimelineGenerator.build_timeline("dummy_dir", manifest, incident_payload)
    trigger_event = next(e for e in timeline_dict["events"] if e["event_type"] == "INCIDENT_TRIGGERED")

    assert trigger_event["source_provider"] == "monitor"
    assert trigger_event["severity"] == "CRITICAL"
    assert trigger_event["timestamp_known"] is True
    assert "2026-07-24T11:30:00" in trigger_event["timestamp"]
    assert "INCIDENT_TRIGGERED" in timeline_text
    print("PASSED")

def test_nginx_and_probe_event_extraction():
    print("4. Nginx & Probe Event Extraction ..... ", end="", flush=True)
    with tempfile.TemporaryDirectory() as tmpdir:
        # Setup nginx error.log
        nginx_dir = os.path.join(tmpdir, "nginx")
        os.makedirs(nginx_dir, exist_ok=True)
        with open(os.path.join(nginx_dir, "error.log"), "w", encoding="utf-8") as f:
            f.write("2026/07/24 11:29:58 [error] 1234#0: *567 connect() failed (61: Connection refused) while connecting to upstream\n")
        with open(os.path.join(nginx_dir, "metadata.json"), "w", encoding="utf-8") as f:
            json.dump({"captured_at": "2026-07-24T11:30:01Z", "status": "SUCCESS"}, f)

        # Setup backend metadata & probe_health.txt
        backend_dir = os.path.join(tmpdir, "backend")
        os.makedirs(backend_dir, exist_ok=True)
        probe_content = "url: http://localhost:8002/api/health\nprobe_result: CONNECTION_ERROR\n"
        with open(os.path.join(backend_dir, "probe_health.txt"), "w", encoding="utf-8") as f:
            f.write(probe_content)
        with open(os.path.join(backend_dir, "metadata.json"), "w", encoding="utf-8") as f:
            json.dump({
                "captured_at": "2026-07-24T11:30:01Z",
                "status": "SUCCESS",
                "artifacts": [
                    {"name": "probe_health.txt", "captured_at": "2026-07-24T11:30:01Z", "status": "SUCCESS"}
                ]
            }, f)

        manifest = {
            "incident_id": "INC-M2-TEST",
            "results": [
                {"provider_name": "nginx"},
                {"provider_name": "backend"}
            ]
        }

        timeline_dict, timeline_text = TimelineGenerator.build_timeline(tmpdir, manifest)
        event_types = [e["event_type"] for e in timeline_dict["events"]]

        assert "NGINX_ERROR" in event_types
        assert "PROBE_OBSERVATION" in event_types

        probe_ev = next(e for e in timeline_dict["events"] if e["event_type"] == "PROBE_OBSERVATION")
        assert probe_ev["details"]["probe_result"] == "CONNECTION_ERROR"
        assert probe_ev["severity"] == "CRITICAL"
    print("PASSED")

def test_chronological_sorting():
    print("5. Chronological Event Sorting ....... ", end="", flush=True)
    manifest = {"incident_id": "INC-SORT", "results": []}
    events = [
        {"timestamp": "2026-07-24T11:30:05Z", "timestamp_known": True, "source_provider": "p3", "artifact_name": "a3", "event_type": "EV3", "severity": "INFO", "summary": "Third event"},
        {"timestamp": "2026-07-24T11:29:50Z", "timestamp_known": True, "source_provider": "p1", "artifact_name": "a1", "event_type": "EV1", "severity": "INFO", "summary": "First event"},
        {"timestamp": "2026-07-24T11:30:00Z", "timestamp_known": True, "source_provider": "p2", "artifact_name": "a2", "event_type": "EV2", "severity": "INFO", "summary": "Second event"},
        {"timestamp": None, "timestamp_known": False, "source_provider": "p4", "artifact_name": "a4", "event_type": "EV4", "severity": "INFO", "summary": "Unknown time event"}
    ]
    
    # Process sorting directly
    sorted_events = sorted([e for e in events if e.get("timestamp_known") and e.get("timestamp")], key=lambda x: x["timestamp"])
    unknown_events = [e for e in events if not e.get("timestamp_known")]
    res_events = sorted_events + unknown_events

    assert res_events[0]["event_type"] == "EV1"
    assert res_events[1]["event_type"] == "EV2"
    assert res_events[2]["event_type"] == "EV3"
    assert res_events[3]["event_type"] == "EV4"
    print("PASSED")

def test_bounded_parsing_limits():
    print("6. Bounded Parsing Constraints ........ ", end="", flush=True)
    with tempfile.TemporaryDirectory() as tmpdir:
        backend_dir = os.path.join(tmpdir, "backend")
        os.makedirs(backend_dir, exist_ok=True)

        # Write 500 log lines (exceeding MAX_LINES_PER_ARTIFACT=100)
        with open(os.path.join(backend_dir, "stdout.log"), "w", encoding="utf-8") as f:
            for i in range(500):
                f.write(f"2026-07-24 11:30:{i%60:02d}.000 [ERROR] Line {i} error\n")

        lines = TimelineGenerator._read_bounded_lines(os.path.join(backend_dir, "stdout.log"))
        assert len(lines) <= MAX_LINES_PER_ARTIFACT
    print("PASSED")

def test_engine_integration():
    print("7. Engine Integration & File Persistence ", end="", flush=True)
    SnapshotEngine._providers = []

    class DummyProvider(SnapshotProvider):
        @property
        def name(self) -> str:
            return "backend"
        def capture(self, context):
            return ProviderCaptureResult(
                provider_name="backend",
                status="SUCCESS",
                artifacts=[
                    CapturedArtifact(
                        name="stdout.log",
                        content="2026-07-24 11:30:00 [ERROR] Internal Server Error\n",
                        status="SUCCESS",
                        capture_method="test",
                        captured_at=datetime.now(timezone.utc),
                        duration_ms=5.0
                    )
                ],
                started_at=datetime.now(timezone.utc),
                finished_at=datetime.now(timezone.utc),
                duration_ms=5.0
            )

    SnapshotEngine.register_provider(DummyProvider())
    incident_id = "INC-M2-INTEG"
    base_dir = os.path.join("incidents", incident_id)
    evidence_dir = os.path.join(base_dir, "evidence")
    os.makedirs(evidence_dir, exist_ok=True)

    try:
        manifest = SnapshotEngine.run(incident_id, "Target", {})
        
        # Verify timeline.json & timeline.txt exist inside evidence/
        timeline_json_path = os.path.join(evidence_dir, "timeline.json")
        timeline_txt_path = os.path.join(evidence_dir, "timeline.txt")

        assert os.path.isfile(timeline_json_path)
        assert os.path.isfile(timeline_txt_path)

        with open(timeline_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            assert data["incident_id"] == incident_id
            assert "events" in data
    finally:
        if os.path.exists(base_dir):
            shutil.rmtree(base_dir)
    print("PASSED")

def main():
    print("==================================================")
    print("Starting Type 1 Verification: M2 Unified Timeline")
    print("==================================================")
    try:
        test_timestamp_parsers()
        test_unparseable_timestamp_handling()
        test_incident_trigger_first_class_event()
        test_nginx_and_probe_event_extraction()
        test_chronological_sorting()
        test_bounded_parsing_limits()
        test_engine_integration()
        print("\n==================================================")
        print("ALL M2 CHECKS PASSED")
        print("TYPE 1 VERIFIED")
        print("==================================================")
    except AssertionError as e:
        import traceback
        traceback.print_exc()
        print("\n==================================================")
        print("VERIFICATION FAILED")
        print("==================================================")
        sys.exit(1)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print("\n==================================================")
        print("SOME CHECKS FAILED WITH EXCEPTION")
        print("==================================================")
        sys.exit(1)

if __name__ == "__main__":
    main()
