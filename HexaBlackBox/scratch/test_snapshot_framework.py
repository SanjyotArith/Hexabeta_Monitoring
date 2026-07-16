import sys
import os
import time
import json
import shutil
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

# Adjust search path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.snapshot.models import SnapshotContext, SnapshotProvider, SnapshotResult
from app.snapshot.engine import SnapshotEngine
from app.snapshot.workflow import IncidentWorkflow
from app.incident import Incident

class MockSuccessProvider(SnapshotProvider):
    def __init__(self, name="mock_success", timeout=5.0, data="success payload"):
        self._name = name
        self._timeout = timeout
        self._data = data
        
    @property
    def name(self) -> str:
        return self._name
        
    @property
    def timeout_seconds(self) -> float:
        return self._timeout
        
    def capture(self, context: SnapshotContext) -> str:
        return self._data

class MockExceptionProvider(SnapshotProvider):
    @property
    def name(self) -> str:
        return "mock_exception"
        
    def capture(self, context: SnapshotContext) -> str:
        raise ValueError("Intentional crash")

class MockTimeoutProvider(SnapshotProvider):
    @property
    def name(self) -> str:
        return "mock_timeout"
        
    @property
    def timeout_seconds(self) -> float:
        return 0.1
        
    def capture(self, context: SnapshotContext) -> str:
        time.sleep(0.5)
        return "should timeout"

# Tests

def test_engine_initialization():
    print("1. Snapshot Engine Initialization ....... ", end="", flush=True)
    # Reset providers
    SnapshotEngine._providers = []
    
    # Run engine with zero providers
    manifest = SnapshotEngine.run("INC-TEST-0001", "TargetTest", {})
    assert manifest["snapshot_schema_version"] == 1
    assert manifest["execution_summary"]["total_providers"] == 0
    assert manifest["execution_summary"]["successful"] == 0
    assert manifest["execution_summary"]["failed"] == 0
    assert len(manifest["results"]) == 0
    
    # Cleanup folder
    if os.path.exists("incidents/INC-TEST-0001"):
        shutil.rmtree("incidents/INC-TEST-0001")
        
    print("PASSED")

def test_snapshot_context():
    print("2. Snapshot Context Validation ......... ", end="", flush=True)
    context = SnapshotContext(
        incident_id="INC-C1",
        target_name="TargetC1",
        config={"test": True},
        evidence_dir="path/dir",
        timestamp=datetime.now(timezone.utc),
        logger=None
    )
    assert context.incident_id == "INC-C1"
    assert context.target_name == "TargetC1"
    assert context.config == {"test": True}
    assert context.evidence_dir == "path/dir"
    assert isinstance(context.timestamp, datetime)
    print("PASSED")

def test_provider_registration():
    print("3. Provider Registration ............... ", end="", flush=True)
    SnapshotEngine._providers = []
    
    p1 = MockSuccessProvider("p1")
    p2 = MockSuccessProvider("p2")
    
    SnapshotEngine.register_provider(p1)
    SnapshotEngine.register_provider(p2)
    # Duplicate registration check
    SnapshotEngine.register_provider(p1)
    
    assert len(SnapshotEngine._providers) == 2
    assert SnapshotEngine._providers[0] == p1
    assert SnapshotEngine._providers[1] == p2
    print("PASSED")

def test_evidence_directory_creation():
    print("4. Evidence Directory Creation ......... ", end="", flush=True)
    SnapshotEngine._providers = []
    p = MockSuccessProvider("test_dir")
    SnapshotEngine.register_provider(p)
    
    incident_id = "INC-TEST-DIR"
    manifest = SnapshotEngine.run(incident_id, "Target", {})
    
    # Check directory structure exists
    evidence_dir = os.path.join("incidents", incident_id, "evidence")
    provider_dir = os.path.join(evidence_dir, "test_dir")
    assert os.path.isdir(evidence_dir)
    assert os.path.isdir(provider_dir)
    
    if os.path.exists(f"incidents/{incident_id}"):
        shutil.rmtree(f"incidents/{incident_id}")
    print("PASSED")

def test_manifest_generation():
    print("5. Manifest Generation ................. ", end="", flush=True)
    SnapshotEngine._providers = []
    p1 = MockSuccessProvider("p1", data="p1 data")
    p2 = MockSuccessProvider("p2", data="p2 data")
    SnapshotEngine.register_provider(p1)
    SnapshotEngine.register_provider(p2)
    
    incident_id = "INC-MANIFEST"
    manifest = SnapshotEngine.run(incident_id, "Target", {})
    
    # Read manifest file
    manifest_path = os.path.join("incidents", incident_id, "evidence", "manifest.json")
    assert os.path.isfile(manifest_path)
    
    with open(manifest_path, "r") as f:
        data = json.load(f)
        
    assert data["snapshot_schema_version"] == 1
    assert data["incident_id"] == incident_id
    assert data["execution_summary"]["total_providers"] == 2
    assert data["execution_summary"]["successful"] == 2
    assert data["execution_summary"]["failed"] == 0
    assert len(data["results"]) == 2
    
    if os.path.exists(f"incidents/{incident_id}"):
        shutil.rmtree(f"incidents/{incident_id}")
    print("PASSED")

def test_engine_managed_storage():
    print("6. Engine-Managed Storage ............. ", end="", flush=True)
    SnapshotEngine._providers = []
    p = MockSuccessProvider("p_storage", data="storage payload")
    SnapshotEngine.register_provider(p)
    
    incident_id = "INC-STORAGE"
    SnapshotEngine.run(incident_id, "Target", {})
    
    # Verify outputs written by engine
    provider_dir = os.path.join("incidents", incident_id, "evidence", "p_storage")
    capture_file = os.path.join(provider_dir, "capture.log")
    metadata_file = os.path.join(provider_dir, "metadata.json")
    
    assert os.path.isfile(capture_file)
    assert os.path.isfile(metadata_file)
    
    with open(capture_file, "r") as f:
        assert f.read() == "storage payload"
        
    with open(metadata_file, "r") as f:
        meta = json.load(f)
        assert meta["provider"] == "p_storage"
        assert meta["status"] == "SUCCESS"
        assert meta["bytes_written"] == len("storage payload")
        
    if os.path.exists(f"incidents/{incident_id}"):
        shutil.rmtree(f"incidents/{incident_id}")
    print("PASSED")

def test_exception_isolation():
    print("7. Exception Isolation ................. ", end="", flush=True)
    SnapshotEngine._providers = []
    p_fail = MockExceptionProvider()
    p_ok = MockSuccessProvider("p_ok", data="ok data")
    SnapshotEngine.register_provider(p_fail)
    SnapshotEngine.register_provider(p_ok)
    
    incident_id = "INC-EXCEPTION"
    # Running should complete successfully without raising exception
    manifest = SnapshotEngine.run(incident_id, "Target", {})
    
    assert manifest["execution_summary"]["successful"] == 1
    assert manifest["execution_summary"]["failed"] == 1
    
    results = {r["provider_name"]: r for r in manifest["results"]}
    assert results["mock_exception"]["status"] == "FAILED"
    assert "Intentional crash" in results["mock_exception"]["error_message"]
    assert results["p_ok"]["status"] == "SUCCESS"
    assert os.path.isfile(os.path.join("incidents", incident_id, "evidence", "p_ok", "capture.log"))
    
    if os.path.exists(f"incidents/{incident_id}"):
        shutil.rmtree(f"incidents/{incident_id}")
    print("PASSED")

def test_timeout_handling():
    print("8. Timeout Handling .................... ", end="", flush=True)
    SnapshotEngine._providers = []
    p_timeout = MockTimeoutProvider()
    p_ok = MockSuccessProvider("p_ok", data="ok")
    SnapshotEngine.register_provider(p_timeout)
    SnapshotEngine.register_provider(p_ok)
    
    incident_id = "INC-TIMEOUT"
    manifest = SnapshotEngine.run(incident_id, "Target", {})
    
    assert manifest["execution_summary"]["successful"] == 1
    assert manifest["execution_summary"]["failed"] == 1
    
    results = {r["provider_name"]: r for r in manifest["results"]}
    assert results["mock_timeout"]["status"] == "TIMEOUT"
    assert results["p_ok"]["status"] == "SUCCESS"
    
    if os.path.exists(f"incidents/{incident_id}"):
        shutil.rmtree(f"incidents/{incident_id}")
    print("PASSED")

def test_incident_persistence_order():
    print("9. Incident Persistence Order .......... ", end="", flush=True)
    
    import app.storage
    execution_timeline = []
    
    # We patch save_incident_payload to log when the incident.json is written
    original_save = app.storage.save_incident_payload
    def spy_save(incident_id, payload):
        execution_timeline.append("incident_json_written")
        original_save(incident_id, payload)
        
    # We patch SnapshotEngine.run to log when it executes
    original_run = SnapshotEngine.run
    def spy_run(incident_id, target_name, config):
        execution_timeline.append("snapshot_engine_executed")
        return original_run(incident_id, target_name, config)
        
    with patch("app.storage.save_incident_payload", side_effect=spy_save):
        with patch.object(SnapshotEngine, "run", side_effect=spy_run):
            config = {
                "targets": [{"name": "TestOrder", "endpoint": "http://api", "interval": 1}],
                "incident": {"verification_attempts": 1, "verification_delay": 1},
                "collectors": {}
            }
            
            incident = IncidentWorkflow.trigger_created(
                target_name="TestOrder",
                failure_reason="HTTP status code 500",
                verification_attempts=1,
                config=config,
                notifier=None
            )
            
            # Assert timing: incident.json must be written before SnapshotEngine execution starts
            assert len(execution_timeline) == 2
            assert execution_timeline[0] == "incident_json_written"
            assert execution_timeline[1] == "snapshot_engine_executed"
            
            if os.path.exists(f"incidents/{incident.id}"):
                shutil.rmtree(f"incidents/{incident.id}")
                
    print("PASSED")

def test_backward_compatibility():
    print("10. Backward Compatibility ............. ", end="", flush=True)
    # Check that calling create_incident directly functions exactly as before
    from app.incident import create_incident
    
    config = {
        "targets": [{"name": "CompTest", "endpoint": "http://api", "interval": 1}],
        "incident": {"verification_attempts": 1, "verification_delay": 1},
        "collectors": {}
    }
    
    incident = create_incident(
        target_name="CompTest",
        failure_reason="Test reason",
        verification_attempts=1,
        config=config,
        notifier=None
    )
    
    assert incident is not None
    assert incident.target_name == "CompTest"
    
    # Assert no evidence directory was created via create_incident since snapshots are decoupled to workflow
    evidence_dir = os.path.join("incidents", incident.id, "evidence")
    assert not os.path.exists(evidence_dir)
    
    if os.path.exists(f"incidents/{incident.id}"):
        shutil.rmtree(f"incidents/{incident.id}")
    print("PASSED")

def test_negative_scenarios():
    print("11. Negative Tests Validation .......... ", end="", flush=True)
    SnapshotEngine._providers = []
    
    # One empty payload provider
    p_empty = MockSuccessProvider("p_empty", data="")
    SnapshotEngine.register_provider(p_empty)
    
    incident_id = "INC-NEGATIVE"
    manifest = SnapshotEngine.run(incident_id, "Target", {})
    
    # Empty capture doesn't create file but runs successfully
    assert manifest["execution_summary"]["successful"] == 1
    assert not os.path.exists(f"incidents/{incident_id}/evidence/p_empty/capture.log")
    
    if os.path.exists(f"incidents/{incident_id}"):
        shutil.rmtree(f"incidents/{incident_id}")
    print("PASSED")

def test_platform_agnostic_confirmation():
    print("12. Platform-Agnostic Confirmation ..... ", end="", flush=True)
    import re
    snapshot_dir = "app/snapshot"
    banned_terms = ["launchctl", "tail", "redis-cli", "psql", "nginx", "cloudflared", "subprocess.Popen", "subprocess.run"]
    
    for filename in os.listdir(snapshot_dir):
        if filename.endswith(".py"):
            with open(os.path.join(snapshot_dir, filename), "r") as f:
                content = f.read()
            # Enforce ps boundary checks
            assert not re.search(r"\bps\b", content), f"Found platform-specific implementation or process run code: 'ps' in {filename}"
            for term in banned_terms:
                assert term not in content, f"Found platform-specific implementation or process run code: '{term}' in {filename}"
                
    print("PASSED")

def main():
    print("==================================================")
    print("Starting Type 1 Verification (Milestone 9 - Batch 1)")
    print("==================================================")
    try:
        test_engine_initialization()
        test_snapshot_context()
        test_provider_registration()
        test_evidence_directory_creation()
        test_manifest_generation()
        test_engine_managed_storage()
        test_exception_isolation()
        test_timeout_handling()
        test_incident_persistence_order()
        test_backward_compatibility()
        test_negative_scenarios()
        test_platform_agnostic_confirmation()
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
