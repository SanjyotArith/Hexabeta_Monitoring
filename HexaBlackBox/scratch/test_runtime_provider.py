import sys
import os
import time
import json
import shutil
import subprocess
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

# Adjust search path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.snapshot.models import SnapshotContext, SnapshotProvider, CapturedArtifact, ProviderCaptureResult
from app.snapshot.engine import SnapshotEngine
from app.snapshot.providers.runtime import RuntimeSnapshotProvider, _redact_process_line

PASS = "\033[32mPASSED\033[0m"
FAIL = "\033[31mFAILED\033[0m"

_PASS_COUNT = 0
_FAIL_COUNT = 0

def _ok(label: str) -> None:
    global _PASS_COUNT
    _PASS_COUNT += 1
    print(f"{label} {PASS}")

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

# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

def test_1_provider_name():
    label = "Test 1: Provider name registration ...... "
    provider = RuntimeSnapshotProvider()
    assert provider.name == "runtime"
    assert provider.timeout_seconds == 5.0
    _ok(label)

def test_2_engine_registration():
    label = "Test 2: Engine registration unique ..... "
    SnapshotEngine._providers = []
    p1 = RuntimeSnapshotProvider()
    p2 = RuntimeSnapshotProvider()
    SnapshotEngine.register_provider(p1)
    SnapshotEngine.register_provider(p2)
    assert len(SnapshotEngine._providers) == 1
    assert SnapshotEngine._providers[0] is p1
    _ok(label)

def test_3_non_macos_stub_behavior():
    label = "Test 3: OS platform constraint guard ... "
    provider = RuntimeSnapshotProvider()
    context = SnapshotContext(
        incident_id="INC-OS-TEST",
        target_name="Target",
        config={},
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    with patch("sys.platform", "linux"):
        res = provider.capture(context)
        assert res.status == "FAILED"
        assert "only supported on macOS" in res.error_message
        assert len(res.artifacts) == 0
    _ok(label)

def test_4_process_line_redaction():
    label = "Test 4: Process credential redaction .... "
    raw = "python3 -m uvicorn app.main:app --port 8002 --password=mysecret -p 123 --token secret_tok"
    redacted = _redact_process_line(raw)
    assert "mysecret" not in redacted
    assert "<REDACTED>" in redacted
    assert "secret_tok" not in redacted
    _ok(label)

def test_5_default_configuration():
    label = "Test 5: Sensible default resolution .... "
    provider = RuntimeSnapshotProvider()
    context = SnapshotContext(
        incident_id="INC-CFG-DEF",
        target_name="Target",
        config={},
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    
    # Mocking launchctl and ps commands to return empty outputs quickly
    with patch("sys.platform", "darwin"), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="header\n", stderr="")
        res = provider.capture(context)
        assert res.status == "SUCCESS"
        assert len(res.artifacts) == 5
        
        # Verify launchctl command was called with the correct production default label
        launchctl_call = mock_run.call_args_list[0][0][0]
        assert "launchctl" in launchctl_call
        assert "gui/501/com.hexa.backend" in launchctl_call or f"gui/{os.getuid()}/com.hexa.backend" in launchctl_call
    _ok(label)

def test_6_config_override_loading():
    label = "Test 6: Provider configuration override . "
    provider = RuntimeSnapshotProvider()
    config = {
        "snapshot": {
            "providers": {
                "runtime": {
                    "launchd_label": "custom.label.test",
                    "launchd_uid": 1001,
                    "expected_command_contains": ["custom_proc"]
                }
            }
        }
    }
    context = SnapshotContext(
        incident_id="INC-CFG-OVR",
        target_name="Target",
        config=config,
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    with patch("sys.platform", "darwin"), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="header\n", stderr="")
        provider.capture(context)
        
        launchctl_call = mock_run.call_args_list[0][0][0]
        assert "gui/1001/custom.label.test" in launchctl_call
    _ok(label)

def test_7_launchctl_print_success():
    label = "Test 7: launchctl_print artifact parsing  "
    provider = RuntimeSnapshotProvider()
    context = SnapshotContext(
        incident_id="INC-L-PRINT",
        target_name="Target",
        config={},
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    with patch("sys.platform", "darwin"), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="com.hexa.backend = {\n pid = 4000\n}", stderr="")
        res = provider.capture(context)
        
        art = next(a for a in res.artifacts if a.name == "launchctl_print.txt")
        assert art.status == "SUCCESS"
        assert "pid = 4000" in art.content
        assert art.exit_code == 0
    _ok(label)

def test_8_launchctl_blame_behavior():
    label = "Test 8: launchctl_blame command check ... "
    provider = RuntimeSnapshotProvider()
    context = SnapshotContext(
        incident_id="INC-L-BLAME",
        target_name="Target",
        config={},
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    with patch("sys.platform", "darwin"), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="active (keepalive)", stderr="")
        res = provider.capture(context)
        
        art = next(a for a in res.artifacts if a.name == "launchctl_blame.txt")
        assert art.status == "SUCCESS"
        assert "keepalive" in art.content
        assert art.exit_code == 0
    _ok(label)

def test_9_launchctl_list_artifact():
    label = "Test 9: launchctl_list command capture .. "
    provider = RuntimeSnapshotProvider()
    context = SnapshotContext(
        incident_id="INC-L-LIST",
        target_name="Target",
        config={},
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    with patch("sys.platform", "darwin"), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="123  0  com.hexablackbox.monitor", stderr="")
        res = provider.capture(context)
        
        art = next(a for a in res.artifacts if a.name == "launchctl_list.txt")
        assert art.status == "SUCCESS"
        assert "com.hexablackbox.monitor" in art.content
    _ok(label)

def test_10_backend_process_extraction():
    label = "Test 10: backend_process.txt structure ... "
    provider = RuntimeSnapshotProvider()
    context = SnapshotContext(
        incident_id="INC-B-PROC",
        target_name="Target",
        config={},
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    
    ps_stdout = (
        "  PID  PPID  PGID STATE %CPU %MEM START TIME COMMAND\n"
        "61000     1 61000   S    0.2  1.5 12:00 00:01 python -m uvicorn app.main:app\n"
        "61001 61000 61000   R    0.5  2.0 12:00 00:02 python -m uvicorn app.main:app (worker)\n"
    )
    
    with patch("sys.platform", "darwin"), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=ps_stdout, stderr="")
        res = provider.capture(context)
        
        art = next(a for a in res.artifacts if a.name == "backend_process.txt")
        assert art.status == "SUCCESS"
        assert "61000" in art.content
        assert "61001" in art.content
        assert "STATE" in art.content
    _ok(label)

def test_11_process_tree_generation():
    label = "Test 11: process_tree hierarchy build ... "
    provider = RuntimeSnapshotProvider()
    context = SnapshotContext(
        incident_id="INC-P-TREE",
        target_name="Target",
        config={},
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    
    ps_stdout = (
        "  PID  PPID  PGID STATE %CPU %MEM START TIME COMMAND\n"
        "61000     1 61000   S    0.2  1.5 12:00 00:01 python -m uvicorn app.main:app\n"
        "61001 61000 61000   R    0.5  2.0 12:00 00:02 python -m uvicorn app.main:app (worker)\n"
    )
    
    with patch("sys.platform", "darwin"), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=ps_stdout, stderr="")
        res = provider.capture(context)
        
        art = next(a for a in res.artifacts if a.name == "process_tree.txt")
        assert art.status == "SUCCESS"
        assert "└── [PID 61000]" in art.content
        assert "    └── [PID 61001]" in art.content
    _ok(label)

def test_12_subprocess_timeout_behavior():
    label = "Test 12: Individual subprocess timeout .. "
    provider = RuntimeSnapshotProvider()
    context = SnapshotContext(
        incident_id="INC-SUB-TO",
        target_name="Target",
        config={},
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    with patch("sys.platform", "darwin"), \
         patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["launchctl"], timeout=1.5)):
        res = provider.capture(context)
        
        art = next(a for a in res.artifacts if a.name == "launchctl_print.txt")
        assert art.status == "TIMEOUT"
        assert "timed out" in art.error_message
    _ok(label)

def test_13_missing_executables_behavior():
    label = "Test 13: Missing tool executables safe . "
    provider = RuntimeSnapshotProvider()
    context = SnapshotContext(
        incident_id="INC-MISS-EXE",
        target_name="Target",
        config={},
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    with patch("sys.platform", "darwin"), \
         patch("subprocess.run", side_effect=FileNotFoundError("launchctl not found")):
        res = provider.capture(context)
        
        art = next(a for a in res.artifacts if a.name == "launchctl_print.txt")
        assert art.status == "SUCCESS"
        assert "Command not found" in art.content
    _ok(label)

def test_14_partial_artifact_failures():
    label = "Test 14: Partial provider success state . "
    provider = RuntimeSnapshotProvider()
    context = SnapshotContext(
        incident_id="INC-PARTIAL",
        target_name="Target",
        config={},
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    
    # 2 calls succeed, next 3 raise exceptions
    run_effects = [
        MagicMock(returncode=0, stdout="print", stderr=""),
        MagicMock(returncode=0, stdout="blame", stderr=""),
        OSError("failed list"),
        OSError("failed ps"),
    ]
    with patch("sys.platform", "darwin"), \
         patch("subprocess.run", side_effect=run_effects):
        res = provider.capture(context)
        assert res.status == "PARTIAL"
    _ok(label)

def test_15_engine_integration_metadata():
    label = "Test 15: Engine metadata generation ..... "
    SnapshotEngine._providers = []
    provider = RuntimeSnapshotProvider()
    SnapshotEngine.register_provider(provider)
    
    incident_id = "INC-META-TEST"
    setup_clean_evidence_dir(incident_id)
    
    ps_stdout = "  PID  PPID  PGID STATE %CPU %MEM START TIME COMMAND\n61000 1 61000 S 0.2 1.5 12:00 00:01 python -m uvicorn app.main:app\n"
    
    try:
        with patch("sys.platform", "darwin"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=ps_stdout, stderr="")
            SnapshotEngine.run(incident_id, "Target", {})
            
        metadata_path = os.path.join("incidents", incident_id, "evidence", "runtime", "metadata.json")
        assert os.path.isfile(metadata_path)
        with open(metadata_path, "r") as f:
            metadata = json.load(f)
            
        assert metadata["provider"] == "runtime"
        assert metadata["status"] == "SUCCESS"
        
        # Verify custom_runtime_metadata is merged
        assert "custom_runtime_metadata" in metadata
        custom = metadata["custom_runtime_metadata"]
        assert custom["backend_found"] is True
        assert custom["commands_executed"] == 4
    finally:
        cleanup_evidence_dir(incident_id)
    _ok(label)

def test_16_engine_integration_manifest():
    label = "Test 16: Engine manifest serialization ... "
    SnapshotEngine._providers = []
    provider = RuntimeSnapshotProvider()
    SnapshotEngine.register_provider(provider)
    
    incident_id = "INC-MAN-TEST"
    setup_clean_evidence_dir(incident_id)
    
    try:
        with patch("sys.platform", "darwin"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="header\n", stderr="")
            SnapshotEngine.run(incident_id, "Target", {})
            
        manifest_path = os.path.join("incidents", incident_id, "evidence", "manifest.json")
        assert os.path.isfile(manifest_path)
        with open(manifest_path, "r") as f:
            manifest = json.load(f)
            
        assert manifest["snapshot_schema_version"] == 1
        runtime_res = next(r for r in manifest["results"] if r["provider_name"] == "runtime")
        assert runtime_res["status"] == "SUCCESS"
    finally:
        cleanup_evidence_dir(incident_id)
    _ok(label)

def test_17_atomic_writes_cleanup():
    label = "Test 17: Temp write files cleanup ...... "
    SnapshotEngine._providers = []
    provider = RuntimeSnapshotProvider()
    SnapshotEngine.register_provider(provider)
    
    incident_id = "INC-WRITE-TEST"
    evidence_dir = setup_clean_evidence_dir(incident_id)
    
    try:
        with patch("sys.platform", "darwin"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="header\n", stderr="")
            SnapshotEngine.run(incident_id, "Target", {})
            
        # Ensure no .tmp files survive in the directory structure
        for root, dirs, files in os.walk(evidence_dir):
            for file in files:
                assert not file.endswith(".tmp")
    finally:
        cleanup_evidence_dir(incident_id)
    _ok(label)

def test_18_redaction_flow_verification():
    label = "Test 18: Redacted output verification ... "
    provider = RuntimeSnapshotProvider()
    context = SnapshotContext(
        incident_id="INC-REDACT-T",
        target_name="Target",
        config={},
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    with patch("sys.platform", "darwin"), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="password=secret token=abc Authorization: Bearer jwttok", stderr="")
        res = provider.capture(context)
        
        art = next(a for a in res.artifacts if a.name == "launchctl_print.txt")
        assert "secret" not in art.content
        assert "jwttok" not in art.content
    _ok(label)

def test_19_provider_isolation_failure():
    label = "Test 19: Provider isolation crash guard . "
    SnapshotEngine._providers = []
    
    class CrashProvider(SnapshotProvider):
        @property
        def name(self) -> str:
            return "crashing"
        def capture(self, context: SnapshotContext):
            raise RuntimeError("Fatal provider failure")
            
    p_fail = CrashProvider()
    p_runtime = RuntimeSnapshotProvider()
    
    SnapshotEngine.register_provider(p_fail)
    SnapshotEngine.register_provider(p_runtime)
    
    incident_id = "INC-ISO-TEST"
    setup_clean_evidence_dir(incident_id)
    
    try:
        with patch("sys.platform", "darwin"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="header\n", stderr="")
            manifest = SnapshotEngine.run(incident_id, "Target", {})
            
        assert manifest["execution_summary"]["total_providers"] == 2
        assert manifest["execution_summary"]["failed"] == 1
        assert manifest["execution_summary"]["successful"] == 1
    finally:
        cleanup_evidence_dir(incident_id)
    _ok(label)

def test_20_stale_files_clearing():
    label = "Test 20: Stale artifacts cleared ....... "
    SnapshotEngine._providers = []
    provider = RuntimeSnapshotProvider()
    SnapshotEngine.register_provider(provider)
    
    incident_id = "INC-STALE-T"
    setup_clean_evidence_dir(incident_id)
    
    # Pre-create stale artifact file
    runtime_dir = os.path.join("incidents", incident_id, "evidence", "runtime")
    os.makedirs(runtime_dir, exist_ok=True)
    stale_file = os.path.join(runtime_dir, "stale_artifact.txt")
    with open(stale_file, "w") as f:
        f.write("stale-data")
        
    try:
        with patch("sys.platform", "darwin"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="header\n", stderr="")
            SnapshotEngine.run(incident_id, "Target", {})
            
        # Stale file should be deleted during pre-clean phase
        assert not os.path.exists(stale_file)
    finally:
        cleanup_evidence_dir(incident_id)
    _ok(label)

def test_21_overall_timeout_handling():
    label = "Test 21: Overall provider timeout isolation "
    SnapshotEngine._providers = []
    
    class SlowRuntimeProvider(RuntimeSnapshotProvider):
        @property
        def timeout_seconds(self) -> float:
            return 0.1
        def capture(self, context: SnapshotContext) -> ProviderCaptureResult:
            time.sleep(0.5)
            return super().capture(context)
            
    provider = SlowRuntimeProvider()
    SnapshotEngine.register_provider(provider)
    
    incident_id = "INC-SLOW-T"
    setup_clean_evidence_dir(incident_id)
    
    try:
        manifest = SnapshotEngine.run(incident_id, "Target", {})
        runtime_res = next(r for r in manifest["results"] if r["provider_name"] == "runtime")
        assert runtime_res["status"] == "TIMEOUT"
    finally:
        cleanup_evidence_dir(incident_id)
    _ok(label)

def test_22_empty_result_safety():
    label = "Test 22: Empty command responses safety . "
    provider = RuntimeSnapshotProvider()
    context = SnapshotContext(
        incident_id="INC-EMPTY-R",
        target_name="Target",
        config={},
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    with patch("sys.platform", "darwin"), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
        res = provider.capture(context)
        
        art = next(a for a in res.artifacts if a.name == "launchctl_print.txt")
        assert art.status == "SUCCESS"
        assert art.content == ""
    _ok(label)

# ---------------------------------------------------------------------------
# Main Runner
# ---------------------------------------------------------------------------

def main():
    print("==================================================")
    print("Starting Type 1 Verification: Runtime Provider")
    print("==================================================")
    try:
        test_1_provider_name()
        test_2_engine_registration()
        test_3_non_macos_stub_behavior()
        test_4_process_line_redaction()
        test_5_default_configuration()
        test_6_config_override_loading()
        test_7_launchctl_print_success()
        test_8_launchctl_blame_behavior()
        test_9_launchctl_list_artifact()
        test_10_backend_process_extraction()
        test_11_process_tree_generation()
        test_12_subprocess_timeout_behavior()
        test_13_missing_executables_behavior()
        test_14_partial_artifact_failures()
        test_15_engine_integration_metadata()
        test_16_engine_integration_manifest()
        test_17_atomic_writes_cleanup()
        test_18_redaction_flow_verification()
        test_19_provider_isolation_failure()
        test_20_stale_files_clearing()
        test_21_overall_timeout_handling()
        test_22_empty_result_safety()
        
        print("\n==================================================")
        print(f"ALL {_PASS_COUNT} CHECKS PASSED")
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
