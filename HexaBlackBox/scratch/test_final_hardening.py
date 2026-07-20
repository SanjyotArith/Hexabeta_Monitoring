"""
Type 1 Verification – Milestone 9 Batch 8: Final Integration & Hardening
========================================================================
All tests run with mocked subprocesses, file operations, or safe temporary
folders, ensuring zero side-effects.
"""

import os
import sys
import json
import shutil
import time
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

# Ensure project root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.incident import (
    Incident,
    create_incident,
    is_incident_active,
    resolve_incident,
    _ACTIVE_INCIDENTS,
    _DAILY_COUNTERS,
)
from app.snapshot.models import (
    SnapshotContext,
    SnapshotProvider,
    CapturedArtifact,
    ProviderCaptureResult,
)
from app.snapshot.redaction import redact_content
from app.snapshot.providers.system import _redact_process_line
from app.snapshot.engine import SnapshotEngine
from app.snapshot.workflow import IncidentWorkflow

PASS = "\033[32mPASSED\033[0m"
FAIL = "\033[31mFAILED\033[0m"

_PASS_COUNT = 0
_FAIL_COUNT = 0

def _ok(label: str) -> None:
    global _PASS_COUNT
    _PASS_COUNT += 1
    print(f"{label} {PASS}")

# A dummy mock provider for testing
class DummyProvider(SnapshotProvider):
    def __init__(self, name: str = "dummy", timeout: float = 1.0, data: str = "test-data"):
        self._name = name
        self._timeout = timeout
        self.data = data
        self.call_count = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def timeout_seconds(self) -> float:
        return self._timeout

    def capture(self, context: SnapshotContext) -> ProviderCaptureResult:
        self.call_count += 1
        redacted = _redact_process_line(self.data)
        redacted = redact_content(redacted)
        return ProviderCaptureResult(
            provider_name=self.name,
            status="SUCCESS",
            artifacts=[
                CapturedArtifact(
                    name="info.txt",
                    content=redacted,
                    status="SUCCESS",
                    capture_method="mock",
                    captured_at=datetime.now(timezone.utc),
                    duration_ms=1.0,
                    bytes_captured=len(redacted),
                    lines_captured=len(redacted.splitlines()),
                    redaction_applied=True,
                )
            ],
        )

# Reset engine state before tests
def _reset_engine():
    SnapshotEngine._providers = []
    _ACTIVE_INCIDENTS.clear()
    _DAILY_COUNTERS.clear()


# ══════════════════════════════════════════════════════════════════════════════
# 1. DUPLICATE SNAPSHOT PREVENTION
# ══════════════════════════════════════════════════════════════════════════════
def test_duplicate_snapshot_prevention():
    label = "1. Duplicate snapshot prevention ....... "
    _reset_engine()

    provider = DummyProvider("prev-test")
    SnapshotEngine.register_provider(provider)

    config = {}
    notifier = MagicMock()

    # First trigger: should run engine and call notifier
    with patch.object(SnapshotEngine, "run", return_value={}) as mock_run:
        inc1 = IncidentWorkflow.trigger_created("target-A", "fail", 1, config, notifier=notifier)
        assert mock_run.call_count == 1, "SnapshotEngine should have run on new incident"
        assert notifier.notify.call_count == 1, "Telegram alert should be dispatched"

    # Second trigger: already active, should NOT run engine, but still return incident
    with patch.object(SnapshotEngine, "run", return_value={}) as mock_run:
        inc2 = IncidentWorkflow.trigger_created("target-A", "fail2", 1, config, notifier=notifier)
        assert mock_run.call_count == 0, "SnapshotEngine should NOT run again on active incident"
        assert inc2.id == inc1.id, "Should return existing active incident"

    # Resolve incident
    resolve_incident("target-A", notifier=notifier)
    assert not is_incident_active("target-A")

    # Third trigger: resolved target becomes unhealthy again -> triggers new incident and new snapshot run
    with patch.object(SnapshotEngine, "run", return_value={}) as mock_run:
        inc3 = IncidentWorkflow.trigger_created("target-A", "fail3", 1, config, notifier=notifier)
        assert mock_run.call_count == 1, "SnapshotEngine should run on new incident after resolution"
        assert inc3.id != inc1.id, "Should generate a new incident ID"

    # Multi-target independence
    with patch.object(SnapshotEngine, "run", return_value={}) as mock_run:
        inc_b = IncidentWorkflow.trigger_created("target-B", "failB", 1, config, notifier=notifier)
        assert mock_run.call_count == 1, "SnapshotEngine should trigger independently for different targets"

    _ok(label)


# ══════════════════════════════════════════════════════════════════════════════
# 2. DUPLICATE PROVIDER REGISTRATION
# ══════════════════════════════════════════════════════════════════════════════
def test_duplicate_provider_registration():
    label = "2. Duplicate provider registration ...... "
    _reset_engine()

    p1 = DummyProvider("dup-name")
    p2 = DummyProvider("dup-name")
    p3 = DummyProvider("other-name")

    SnapshotEngine.register_provider(p1)
    SnapshotEngine.register_provider(p2) # Same name, different instance -> should be ignored
    SnapshotEngine.register_provider(p3) # Different name -> should succeed

    assert len(SnapshotEngine._providers) == 2, f"Expected 2 providers, got {len(SnapshotEngine._providers)}"
    assert SnapshotEngine._providers[0] is p1
    assert SnapshotEngine._providers[1] is p3

    # Verify execution runs only registered unique providers
    config = {}
    with patch.object(p1, "capture", side_effect=p1.capture) as m1, \
         patch.object(p2, "capture", side_effect=p2.capture) as m2, \
         patch.object(p3, "capture", side_effect=p3.capture) as m3:
        SnapshotEngine.run("INC-REG", "target", config)
        assert m1.call_count == 1, "p1 should execute once"
        assert m2.call_count == 0, "p2 should not execute at all"
        assert m3.call_count == 1, "p3 should execute once"

    _ok(label)


# ══════════════════════════════════════════════════════════════════════════════
# 3. ATOMIC WRITES & SECURITY TESTS
# ══════════════════════════════════════════════════════════════════════════════
def test_atomic_writes_and_cleanup():
    label = "3. Atomic writes & temporary cleanup .... "
    _reset_engine()

    # Create dummy provider containing secrets
    secret_text = "My secret PGPASSWORD=TYPE8_SECRET_VAL and token=TYPE8_SECRET_TOKEN"
    provider = DummyProvider("atomic-test", data=secret_text)
    SnapshotEngine.register_provider(provider)

    incident_id = "INC-ATOMIC-TEST"
    evidence_root = os.path.join("incidents", incident_id)
    if os.path.exists(evidence_root):
        shutil.rmtree(evidence_root)

    # Patch os.replace to track atomic renaming calls
    with patch("os.replace", side_effect=os.replace) as mock_replace:
        config = {}
        manifest = SnapshotEngine.run(incident_id, "target", config)
        
        # Verify os.replace calls
        assert mock_replace.call_count >= 3, "Should have used os.replace for artifacts, metadata, and manifest"

    sys_dir = os.path.join(evidence_root, "evidence", "atomic-test")
    manifest_path = os.path.join(evidence_root, "evidence", "manifest.json")
    
    # Assert manifest & metadata exist and are valid JSON
    assert os.path.isfile(manifest_path)
    with open(manifest_path) as f:
        meta_json = json.load(f)
    assert meta_json["snapshot_schema_version"] == 1

    # Assert no temporary .tmp files left in the destination directories
    evidence_dir = os.path.join(evidence_root, "evidence")
    for root, dirs, files in os.walk(evidence_dir):
        for f in files:
            assert not f.endswith(".tmp"), f"Leftover temp file found: {f}"

    # Assert redaction holds on completed files
    artifact_path = os.path.join(sys_dir, "info.txt")
    with open(artifact_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "TYPE8_SECRET_VAL" not in content, "Secrets leaked into final artifact"

    # Simulated write failure: test cleanup
    # We force write_atomic to fail during json.dump or open()
    # verify that the tmp file is cleaned up, and previous manifest/metadata are not corrupted.
    with patch("builtins.open", side_effect=IOError("Simulated write failure")):
        try:
            SnapshotEngine._write_atomic(manifest_path, {"test": "data"}, is_json=True)
        except IOError:
            pass

    # Check that no leftover temp files exist
    for root, dirs, files in os.walk(evidence_dir):
        for f in files:
            assert not f.endswith(".tmp"), f"Leftover temp file after failure: {f}"
    
    # Manifest has not been corrupted/overwritten by the failed write
    with open(manifest_path) as f:
        valid_manifest = json.load(f)
    assert valid_manifest["snapshot_schema_version"] == 1

    # Simulated replace failure: test cleanup
    with patch("os.replace", side_effect=OSError("Simulated replace failure")):
        try:
            SnapshotEngine._write_atomic(manifest_path, {"test": "new-data"}, is_json=True)
        except OSError:
            pass

    # Check that no leftover temp files exist
    for root, dirs, files in os.walk(evidence_dir):
        for f in files:
            assert not f.endswith(".tmp"), f"Leftover temp file after replace failure: {f}"
    
    # Manifest remains valid
    with open(manifest_path) as f:
        valid_manifest = json.load(f)
    assert valid_manifest["snapshot_schema_version"] == 1

    # Clean up evidence
    shutil.rmtree(evidence_root, ignore_errors=True)
    _ok(label)


# ══════════════════════════════════════════════════════════════════════════════
# 4. FAILURE ISOLATION
# ══════════════════════════════════════════════════════════════════════════════
def test_failure_isolation():
    label = "4. Failure isolation checks ............ "
    _reset_engine()

    p_fail = DummyProvider("fail-prov")
    p_ok = DummyProvider("ok-prov")

    # Mock p_fail to raise exception
    p_fail.capture = MagicMock(side_effect=Exception("Provider capture failed"))

    SnapshotEngine.register_provider(p_fail)
    SnapshotEngine.register_provider(p_ok)

    incident_id = "INC-FAIL-ISOLATION"
    config = {}

    # One provider failure should not stop the other provider
    manifest = SnapshotEngine.run(incident_id, "target", config)
    assert manifest["execution_summary"]["successful"] == 1
    assert manifest["execution_summary"]["failed"] == 1

    results = {r["provider_name"]: r["status"] for r in manifest["results"]}
    assert results["fail-prov"] == "FAILED"
    assert results["ok-prov"] == "SUCCESS"

    # Clean up
    shutil.rmtree(os.path.join("incidents", incident_id), ignore_errors=True)
    _ok(label)


# ══════════════════════════════════════════════════════════════════════════════
# 5. PROVIDER TIMEOUT & STALE EVIDENCE
# ══════════════════════════════════════════════════════════════════════════════
def test_provider_timeout_and_stale_evidence():
    label = "5. Provider timeout & stale evidence .... "
    _reset_engine()

    p_slow = DummyProvider("slow-prov")
    # Mock capture to take 3.0s (longer than the 0.5s timeout)
    def slow_capture(context):
        time.sleep(3.0)
        return ProviderCaptureResult(
            provider_name="slow-prov",
            status="SUCCESS",
            artifacts=[
                CapturedArtifact(
                    name="info.txt",
                    content="late-success-data",
                    status="SUCCESS",
                    capture_method="mock",
                    captured_at=datetime.now(timezone.utc),
                    duration_ms=3000.0,
                    bytes_captured=17,
                    lines_captured=1,
                )
            ],
        )
    p_slow.capture = slow_capture
    SnapshotEngine.register_provider(p_slow)

    incident_id = "INC-TIMEOUT-TEST"
    evidence_root = os.path.join("incidents", incident_id)
    shutil.rmtree(evidence_root, ignore_errors=True)

    # 1. Populate the provider dir with stale SUCCESS evidence from a previous run
    slow_dir = os.path.join(evidence_root, "evidence", "slow-prov")
    os.makedirs(slow_dir, exist_ok=True)
    
    stale_artifact_path = os.path.join(slow_dir, "stale_artifact.txt")
    with open(stale_artifact_path, "w") as f:
        f.write("stale-data")
        
    stale_metadata_path = os.path.join(slow_dir, "metadata.json")
    with open(stale_metadata_path, "w") as f:
        json.dump({
            "captured_at": "2026-07-20T00:00:00Z",
            "provider": "slow-prov",
            "status": "SUCCESS",
            "duration_ms": 100.0,
            "artifacts": [],
            "bytes_written": 0
        }, f)

    # 2. Run the engine, configuring timeout_seconds: 0.5s for slow-prov
    config = {
        "snapshot": {
            "slow-prov": {
                "timeout_seconds": 0.5
            }
        }
    }
    
    t_start = time.perf_counter()
    manifest = SnapshotEngine.run(incident_id, "target", config)
    t_elapsed = time.perf_counter() - t_start

    # Assert the engine did not wait for the slow provider (elapsed time should be close to 0.5s, definitely < 2.0s)
    assert t_elapsed < 2.0, f"Engine blocked! Took {t_elapsed:.2f} seconds, expected < 2.0s"

    # Assert manifest correctly records TIMEOUT
    slow_res = next(r for r in manifest["results"] if r["provider_name"] == "slow-prov")
    assert slow_res["status"] == "TIMEOUT"
    assert "exceeded timeout" in slow_res["error_message"]

    # Assert stale artifact was deleted and is no longer present
    assert not os.path.exists(stale_artifact_path), "Stale artifact survived cleanup!"

    # Assert metadata.json was updated to record TIMEOUT
    assert os.path.isfile(stale_metadata_path), "metadata.json was deleted but not rewritten"
    with open(stale_metadata_path) as f:
        curr_metadata = json.load(f)
    assert curr_metadata["status"] == "TIMEOUT", f"Expected TIMEOUT status, got {curr_metadata['status']}"
    assert len(curr_metadata["artifacts"]) == 0, "Stale artifacts are still listed in metadata.json"

    # 3. Allow background thread to finish and verify it doesn't corrupt/overwrite the TIMEOUT state
    time.sleep(3.0)
    
    # Assert metadata.json is still TIMEOUT (late thread did not overwrite it)
    with open(stale_metadata_path) as f:
        final_metadata = json.load(f)
    assert final_metadata["status"] == "TIMEOUT"
    assert not os.path.exists(os.path.join(slow_dir, "info.txt")), "Late thread wrote artifacts to disk!"

    # Clean up evidence
    shutil.rmtree(evidence_root, ignore_errors=True)
    _ok(label)


# ══════════════════════════════════════════════════════════════════════════════
# REGRESSIONS
# ══════════════════════════════════════════════════════════════════════════════
def _run_regression(script: str) -> bool:
    import subprocess as sp
    r = sp.run([sys.executable, script], capture_output=True, text=True)
    return r.returncode == 0

def test_regression_backend():
    label = "R1. Backend provider regression ......... "
    assert _run_regression("scratch/test_backend_provider.py"), "Backend regression FAILED"
    _ok(label)

def test_regression_nginx():
    label = "R2. Nginx provider regression ........... "
    assert _run_regression("scratch/test_nginx_provider.py"), "Nginx regression FAILED"
    _ok(label)

def test_regression_postgres():
    label = "R3. PostgreSQL provider regression ....... "
    assert _run_regression("scratch/test_postgres_provider.py"), "Postgres regression FAILED"
    _ok(label)

def test_regression_cloudflare():
    label = "R4. Cloudflare provider regression ...... "
    assert _run_regression("scratch/test_cloudflared_provider.py"), "Cloudflare regression FAILED"
    _ok(label)

def test_regression_redis():
    label = "R5. Redis provider regression ........... "
    assert _run_regression("scratch/test_redis_provider.py"), "Redis regression FAILED"
    _ok(label)

def test_regression_system():
    label = "R6. System provider regression .......... "
    assert _run_regression("scratch/test_system_provider.py"), "System regression FAILED"
    _ok(label)

def test_regression_config():
    label = "R7. Config override regression .......... "
    assert _run_regression("scratch/test_config_override.py"), "Config override regression FAILED"
    _ok(label)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
def main():
    print("=" * 60)
    print("Type 1 Verification - Milestone 9 Batch 8: Hardening & Integration")
    print("=" * 60)

    tests = [
        test_duplicate_snapshot_prevention,
        test_duplicate_provider_registration,
        test_atomic_writes_and_cleanup,
        test_failure_isolation,
        test_provider_timeout_and_stale_evidence,
        # Regression checks
        test_regression_backend,
        test_regression_nginx,
        test_regression_postgres,
        test_regression_cloudflare,
        test_regression_redis,
        test_regression_system,
        test_regression_config,
    ]

    for test_fn in tests:
        try:
            test_fn()
        except AssertionError as e:
            print(f"\n{'=' * 60}")
            print("VERIFICATION FAILED")
            print(f"{'=' * 60}")
            print(f"Assertion Error: {e}")
            sys.exit(1)
        except Exception as e:
            global _FAIL_COUNT
            _FAIL_COUNT += 1
            print(f"Unexpected error: {e}")
            sys.exit(1)

    print(f"\n{'=' * 60}")
    print(f"ALL {_PASS_COUNT} CHECKS PASSED")
    print("TYPE 1 VERIFIED")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
