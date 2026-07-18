import sys
import os
import time
import json
import shutil
import re
import subprocess
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

# Adjust search path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.snapshot.models import SnapshotContext, SnapshotProvider, CapturedArtifact, ProviderCaptureResult
from app.snapshot.engine import SnapshotEngine
from app.snapshot.providers.backend import _tail_file, MacOSBackendSnapshotProvider
from app.snapshot.redaction import redact_content

# Helpers

def setup_clean_evidence_dir(incident_id: str) -> str:
    path = os.path.join("incidents", incident_id)
    if os.path.exists(path):
        shutil.rmtree(path)
    os.makedirs(path)
    return path

def cleanup_evidence_dir(incident_id: str):
    path = os.path.join("incidents", incident_id)
    if os.path.exists(path):
        shutil.rmtree(path)

# Tests

def test_structured_artifact_model():
    print("1. Structured Artifact Model ........... ", end="", flush=True)
    art1 = CapturedArtifact(
        name="test.log",
        content="data",
        status="SUCCESS",
        capture_method="test",
        captured_at=datetime.now(timezone.utc),
        duration_ms=10.0
    )
    result = ProviderCaptureResult(
        provider_name="backend",
        status="SUCCESS",
        artifacts=[art1],
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
        duration_ms=10.0
    )
    assert result.status == "SUCCESS"
    assert len(result.artifacts) == 1
    assert result.artifacts[0].name == "test.log"
    print("PASSED")

def test_bounded_log_capture():
    print("2. Bounded Log Capture ................. ", end="", flush=True)
    test_log = "test_tail.log"
    
    # Create a dummy log file
    with open(test_log, "w", encoding="utf-8") as f:
        f.write("line1\nline2\nline3\nline4\nline5\n")
        
    try:
        # Enforce max_lines=3, max_bytes=100
        content, truncated, lines_read, bytes_read = _tail_file(test_log, max_lines=3, max_bytes=100)
        assert content == "line3\nline4\nline5"
        assert truncated is True
        assert lines_read == 3
        assert bytes_read == len("line3\nline4\nline5".encode("utf-8"))
        
        # Test large single line truncation by bytes limit
        with open(test_log, "w", encoding="utf-8") as f:
            f.write("A" * 1000 + "\n")
            
        content, truncated, lines_read, bytes_read = _tail_file(test_log, max_lines=5, max_bytes=10)
        assert len(content) in (8, 9)
        assert truncated is True
        
        # Test missing file error
        try:
            _tail_file("missing_file.log", max_lines=5, max_bytes=100)
            raise AssertionError("Should raise FileNotFoundError")
        except FileNotFoundError:
            pass
            
        # Test empty file
        with open(test_log, "w", encoding="utf-8") as f:
            f.write("")
        content, truncated, lines_read, bytes_read = _tail_file(test_log, max_lines=5, max_bytes=100)
        assert content == ""
        assert truncated is False
        assert lines_read == 0
        assert bytes_read == 0
        
        # Test invalid UTF-8 bytes handling (errors='ignore' fallback)
        with open(test_log, "wb") as f:
            f.write(b"valid line\n\xff\xfe invalid line\n")
        content, truncated, lines_read, bytes_read = _tail_file(test_log, max_lines=5, max_bytes=100)
        assert "valid line" in content
        assert "invalid line" in content
        
    finally:
        if os.path.exists(test_log):
            os.remove(test_log)
            
    print("PASSED")

def test_redaction():
    print("3. Redaction Filters & Security ....... ", end="", flush=True)
    raw_log = (
        "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c\n"
        "Some standalone JWT eyJ1c2VyIjoiYWRtaW4ifQ.eyJycmdzIjpbXX0.abcdef12345 here\n"
        "Request URL: http://localhost:8002/api?token=secret_tok_123&access_token=acc_456&refresh_token=ref_789&id_token=id_abc\n"
        "Cookie: session=sess_xyz123; tracking=track_abc\n"
        "Set-Cookie: session=sess_new; path=/\n"
        "Data: {\"password\": \"super_pass\", \"secret\": \"topsecret\", \"api_key\": \"key123\", \"apikey\": \"key456\"}\n"
        "DB URL: postgresql://postgres:password123@127.0.0.1:5432/hexa_db\n"
    )
    
    redacted = redact_content(raw_log)
    
    # Assert all target credentials are redacted
    assert "eyJhbGciOiJIUzI1Ni" not in redacted
    assert "<REDACTED_JWT>" in redacted
    assert "<REDACTED_TOKEN>" in redacted
    assert "token=<REDACTED>" in redacted
    assert "access_token=<REDACTED>" in redacted
    assert "refresh_token=<REDACTED>" in redacted
    assert "id_token=<REDACTED>" in redacted
    assert "Cookie: <REDACTED>" in redacted
    assert "Set-Cookie: <REDACTED>" in redacted
    assert '"password": "<REDACTED>"' in redacted
    assert '"secret": "<REDACTED>"' in redacted
    assert '"api_key": "<REDACTED>"' in redacted
    assert '"apikey": "<REDACTED>"' in redacted
    assert "postgresql://<REDACTED_CREDS>@127.0.0.1" in redacted
    
    # Execute full Provider -> SnapshotEngine flow to verify no secrets appear on disk
    SnapshotEngine._providers = []
    p = MockSuccessProvider = MacOSBackendSnapshotProvider()
    SnapshotEngine.register_provider(p)
    
    config = {
        "snapshot": {
            "providers": {
                "backend": {
                    "enabled": True,
                    "timeout_seconds": 2,
                    "logs": {
                        "stdout_path": "temp_stdout.log",
                        "stderr_path": "temp_stderr.log",
                        "max_lines": 100,
                        "max_bytes": 10000
                    }
                }
            }
        }
    }
    
    # Create temp log files with secrets
    with open("temp_stdout.log", "w", encoding="utf-8") as f:
        f.write(raw_log)
    with open("temp_stderr.log", "w", encoding="utf-8") as f:
        f.write(raw_log)
        
    incident_id = "INC-REDACT-FLOW"
    setup_clean_evidence_dir(incident_id)
    
    try:
        # Mock other commands to return success
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="clean data", stderr="")
            SnapshotEngine.run(incident_id, "Target", config)
            
        # Read files and verify absence of secrets
        evidence_dir = os.path.join("incidents", incident_id, "evidence")
        backend_dir = os.path.join(evidence_dir, "backend")
        manifest_file = os.path.join(evidence_dir, "manifest.json")
        metadata_file = os.path.join(backend_dir, "metadata.json")
        stdout_file = os.path.join(backend_dir, "stdout.log")
        
        for path in [manifest_file, metadata_file, stdout_file]:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
                assert "eyJhbGciOiJIUzI1Ni" not in content, f"Secret leaked in {path}"
                assert "password123" not in content, f"Secret credentials leaked in {path}"
                assert "super_pass" not in content, f"Secret password leaked in {path}"
                assert "sess_xyz123" not in content, f"Secret session leaked in {path}"
                
    finally:
        cleanup_evidence_dir(incident_id)
        for log in ["temp_stdout.log", "temp_stderr.log"]:
            if os.path.exists(log):
                os.remove(log)
                
    print("PASSED")

def test_launchd_evidence():
    print("4. launchd Evidence Mocks .............. ", end="", flush=True)
    provider = MacOSBackendSnapshotProvider()
    
    # Create dummy SnapshotContext
    context = SnapshotContext(
        incident_id="INC-L1",
        target_name="Target",
        config={
            "snapshot": {
                "providers": {
                    "backend": {
                        "service": {"launchd_label": "com.hexa.backend"}
                    }
                }
            }
        },
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    
    # 1. Success case
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="com.hexa.backend details", stderr="")
        res = provider.capture(context)
        
        launchd_art = next(a for a in res.artifacts if a.name == "launchd.txt")
        assert launchd_art.status == "SUCCESS"
        assert launchd_art.exit_code == 0
        assert launchd_art.content == "com.hexa.backend details"
        # Verify shell=False was used
        launchd_call = False
        for call_args in mock_run.call_args_list:
            args, kwargs = call_args
            if args and args[0] == ["launchctl", "print", f"gui/1000/com.hexa.backend"]:
                assert kwargs.get("shell") is False
                assert kwargs.get("timeout") == 1.0
                launchd_call = True
        assert launchd_call is True
        
    # 2. Timeout case
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["launchctl"], timeout=1.0)):
        res = provider.capture(context)
        launchd_art = next(a for a in res.artifacts if a.name == "launchd.txt")
        assert launchd_art.status == "TIMEOUT"
        assert launchd_art.error_message == "Command execution timed out"
        
    print("PASSED")

def test_process_evidence():
    print("5. Process Evidence Parsing ............ ", end="", flush=True)
    provider = MacOSBackendSnapshotProvider()
    
    context = SnapshotContext(
        incident_id="INC-P1",
        target_name="Target",
        config={
            "snapshot": {
                "providers": {
                    "backend": {
                        "process": {
                            "expected_command_contains": ["uvicorn", "app.main:app"]
                        }
                    }
                }
            }
        },
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    
    # Mock ps command stdout output (contains parent, worker, and an unrelated python script)
    ps_stdout = (
        "  PID  PPID %CPU %MEM COMMAND\n"
        "61000     1  0.2  1.5 python -m uvicorn app.main:app --port 8002\n"
        "61001 61000  0.5  2.0 python -m uvicorn app.main:app --port 8002 (worker)\n"
        "61002 61000  0.5  2.0 python -m uvicorn app.main:app --port 8002 (worker)\n"
        "62000     1  0.1  0.5 python -m unrelated.script\n"
    )
    
    # 1. Backend Present Case
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=ps_stdout, stderr="")
        res = provider.capture(context)
        
        proc_art = next(a for a in res.artifacts if a.name == "processes.txt")
        assert proc_art.status == "SUCCESS"
        # Excludes "unrelated.script", includes uvicorn workers
        assert "61000" in proc_art.content
        assert "61001" in proc_art.content
        assert "61002" in proc_art.content
        assert "62000" not in proc_art.content
        
    # 2. Backend Absent Case (ps output contains only unrelated processes)
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="  PID  PPID %CPU %MEM COMMAND\n62000     1  0.1  0.5 python -m unrelated.script\n", stderr="")
        res = provider.capture(context)
        
        proc_art = next(a for a in res.artifacts if a.name == "processes.txt")
        # Header remains, but no matching backend PIDs
        assert proc_art.status == "SUCCESS"
        assert "62000" not in proc_art.content
        
    print("PASSED")

def test_port_evidence():
    print("6. Port Evidence Parsing .............. ", end="", flush=True)
    provider = MacOSBackendSnapshotProvider()
    
    context = SnapshotContext(
        incident_id="INC-N1",
        target_name="Target",
        config={
            "snapshot": {
                "providers": {
                    "backend": {
                        "network": {"port": 8002}
                    }
                }
            }
        },
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    
    # Mock lsof command output
    lsof_stdout = (
        "COMMAND   PID     USER   FD   TYPE DEVICE SIZE/OFF NODE NAME\n"
        "python3 61000 hexabeta    3u  IPv4  0x...      0t0  TCP 127.0.0.1:8002 (LISTEN)\n"
    )
    
    # 1. Port Listening
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=lsof_stdout, stderr="")
        res = provider.capture(context)
        
        port_art = next(a for a in res.artifacts if a.name == "port.txt")
        assert port_art.status == "SUCCESS"
        assert "61000" in port_art.content
        assert "LISTEN" in port_art.content
        # Verify lsof -n -P was used
        lsof_call = False
        for call_args in mock_run.call_args_list:
            args, kwargs = call_args
            if args and args[0] == ["lsof", "-n", "-P", "-i", "tcp:8002"]:
                assert kwargs.get("shell") is False
                assert kwargs.get("timeout") == 1.0
                lsof_call = True
        assert lsof_call is True
        
    # 2. Port Not Listening (lsof returns exit code 1 / empty stdout)
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
        res = provider.capture(context)
        port_art = next(a for a in res.artifacts if a.name == "port.txt")
        assert port_art.status == "SUCCESS"  # The lsof check executed but returned empty
        assert port_art.content == ""
        
    print("PASSED")

def test_partial_failures_and_timeouts():
    print("7. Partial Failures & Timeouts ......... ", end="", flush=True)
    provider = MacOSBackendSnapshotProvider()
    
    context = SnapshotContext(
        incident_id="INC-FAIL-1",
        target_name="Target",
        config={},
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    
    # 1. One failed command + others successful -> PARTIAL
    with patch("subprocess.run") as mock_run:
        # Simulate stdout logs missing, launchctl failed, processes success, port success
        mock_run.side_effect = [
            MagicMock(returncode=1, stdout="", stderr="command error"), # launchctl print
            MagicMock(returncode=0, stdout="PID COMMAND", stderr=""),     # ps
            MagicMock(returncode=0, stdout="lsof details", stderr="")      # lsof
        ]
        
        res = provider.capture(context)
        assert res.status == "PARTIAL"
        
    # 2. All artifacts failed -> FAILED
    with patch("subprocess.run", side_effect=RuntimeError("Generic shell crash")):
        res = provider.capture(context)
        # Logs also fail because files are missing in this test environment
        assert res.status == "FAILED"
        
    print("PASSED")

def test_storage():
    print("8. Storage Structure & Metadata ........ ", end="", flush=True)
    SnapshotEngine._providers = []
    p = MacOSBackendSnapshotProvider()
    SnapshotEngine.register_provider(p)
    
    incident_id = "INC-STORAGE-TEST"
    setup_clean_evidence_dir(incident_id)
    
    config = {
        "snapshot": {
            "providers": {
                "backend": {
                    "enabled": True,
                    "logs": {
                        "stdout_path": "temp_stdout.log",
                        "stderr_path": "temp_stderr.log"
                    }
                }
            }
        }
    }
    
    # Write temp files
    with open("temp_stdout.log", "w") as f:
        f.write("stdout line\n")
    with open("temp_stderr.log", "w") as f:
        f.write("stderr line\n")
        
    try:
        # Mock CLI commands
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="command out", stderr="")
            SnapshotEngine.run(incident_id, "Target", config)
            
        evidence_dir = os.path.join("incidents", incident_id, "evidence")
        backend_dir = os.path.join(evidence_dir, "backend")
        
        # Verify structure
        assert os.path.isfile(os.path.join(evidence_dir, "manifest.json"))
        assert os.path.isfile(os.path.join(backend_dir, "stdout.log"))
        assert os.path.isfile(os.path.join(backend_dir, "stderr.log"))
        assert os.path.isfile(os.path.join(backend_dir, "launchd.txt"))
        assert os.path.isfile(os.path.join(backend_dir, "processes.txt"))
        assert os.path.isfile(os.path.join(backend_dir, "port.txt"))
        assert os.path.isfile(os.path.join(backend_dir, "metadata.json"))
        
        # Verify manifest.json keys
        with open(os.path.join(evidence_dir, "manifest.json"), "r") as f:
            manifest = json.load(f)
            assert manifest["snapshot_schema_version"] == 1
            assert manifest["execution_summary"]["total_providers"] == 1
            assert manifest["results"][0]["provider_name"] == "backend"
            assert manifest["results"][0]["status"] == "SUCCESS"
            
        # Verify metadata.json keys
        with open(os.path.join(backend_dir, "metadata.json"), "r") as f:
            metadata = json.load(f)
            assert metadata["provider"] == "backend"
            assert metadata["status"] == "SUCCESS"
            assert len(metadata["artifacts"]) == 5
            
            stdout_meta = next(a for a in metadata["artifacts"] if a["name"] == "stdout.log")
            assert stdout_meta["status"] == "SUCCESS"
            assert stdout_meta["bytes_captured"] == len("stdout line")
            assert stdout_meta["lines_captured"] == 1
            assert stdout_meta["truncated"] is False
            assert stdout_meta["redaction_applied"] is True
            
    finally:
        cleanup_evidence_dir(incident_id)
        for log in ["temp_stdout.log", "temp_stderr.log"]:
            if os.path.exists(log):
                os.remove(log)
                
    print("PASSED")

def test_path_traversal_security():
    print("9. Path Traversal Security ............ ", end="", flush=True)
    SnapshotEngine._providers = []
    
    # 1. Verify validate_name blocks traversal strings
    assert SnapshotEngine._validate_name("safe_name") is True
    assert SnapshotEngine._validate_name("../outside") is False
    assert SnapshotEngine._validate_name("..\\outside") is False
    assert SnapshotEngine._validate_name("/absolute/path") is False
    assert SnapshotEngine._validate_name("c:\\absolute") is False
    
    # 2. Test execution aborts for malicious provider name
    class MaliciousProvider(SnapshotProvider):
        @property
        def name(self) -> str:
            return "../evil_provider"
        def capture(self, context: SnapshotContext) -> str:
            return "data"
            
    SnapshotEngine.register_provider(MaliciousProvider())
    manifest = SnapshotEngine.run("INC-TRAVERSAL", "Target", {})
    
    # Assert registration failed / blocked gracefully and logged FAILED status
    assert manifest["execution_summary"]["failed"] == 1
    assert manifest["results"][0]["status"] == "FAILED"
    assert "blocked" in manifest["results"][0]["error_message"]
    assert not os.path.exists("incidents/INC-TRAVERSAL/evidence/evil_provider")
    
    if os.path.exists("incidents/INC-TRAVERSAL"):
        shutil.rmtree("incidents/INC-TRAVERSAL")
        
    print("PASSED")

def test_backward_compatibility():
    print("10. Backward Compatibility ............. ", end="", flush=True)
    # Check that flat string providers (Batch 1 behavior) still write capture.log correctly
    SnapshotEngine._providers = []
    
    class FlatStringProvider(SnapshotProvider):
        @property
        def name(self) -> str:
            return "flat_provider"
        def capture(self, context: SnapshotContext) -> str:
            return "flat log content"
            
    SnapshotEngine.register_provider(FlatStringProvider())
    incident_id = "INC-COMPAT"
    setup_clean_evidence_dir(incident_id)
    
    try:
        manifest = SnapshotEngine.run(incident_id, "Target", {})
        assert manifest["execution_summary"]["successful"] == 1
        assert manifest["results"][0]["status"] == "SUCCESS"
        
        # Verify capture.log is written
        provider_dir = os.path.join("incidents", incident_id, "evidence", "flat_provider")
        assert os.path.isfile(os.path.join(provider_dir, "capture.log"))
        assert os.path.isfile(os.path.join(provider_dir, "metadata.json"))
        
        with open(os.path.join(provider_dir, "capture.log"), "r") as f:
            assert f.read() == "flat log content"
            
    finally:
        cleanup_evidence_dir(incident_id)
        
    print("PASSED")

def test_observer_only_safety():
    print("11. Observer-Only Safety Audit ........ ", end="", flush=True)
    # Verify no mutating process words exist inside app/snapshot/providers/backend.py
    backend_file = "app/snapshot/providers/backend.py"
    mutating_terms = ["kill", "terminate", "hb-start", "hb-stop", "kickstart", "bootstrap", "bootout", "os.system"]
    
    with open(backend_file, "r") as f:
        content = f.read()
        
    # We must allow comments or method signatures but check if subprocess or mutating calls exist
    # e.g., we check that "launchctl" is only print/read-only:
    # "launchctl print" is the only arg array.
    for term in mutating_terms:
        # Exclude expected launchd print comment mentions
        if term in ("bootstrap", "bootout", "kickstart", "kill"):
            # Ensure they only occur inside comments (lines starting with # or within triple quotes)
            lines = content.splitlines()
            for idx, line in enumerate(lines):
                if term in line:
                    trimmed = line.strip()
                    assert trimmed.startswith("#") or "NOTE:" in trimmed or "provider must NEVER" in trimmed or "Directly terminating" in trimmed, \
                        f"Mutating term '{term}' found in executable line {idx+1}: {line}"
        else:
            assert term not in content, f"Banned mutating term '{term}' found in {backend_file}"
            
    print("PASSED")

def main():
    print("==================================================")
    print("Starting Type 1 Verification (Milestone 9 - Batch 2)")
    print("==================================================")
    try:
        test_structured_artifact_model()
        test_bounded_log_capture()
        test_redaction()
        test_launchd_evidence()
        test_process_evidence()
        test_port_evidence()
        test_partial_failures_and_timeouts()
        test_storage()
        test_path_traversal_security()
        test_backward_compatibility()
        test_observer_only_safety()
        print("\n==================================================")
        print("ALL CHECKS PASSED")
        print("TYPE 1 VERIFIED")
        print("==================================================")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print("\n==================================================")
        print("SOME CHECKS FAILED")
        print("==================================================")

if __name__ == "__main__":
    main()
