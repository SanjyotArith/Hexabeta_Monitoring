import sys
import os
import json
import shutil
from unittest.mock import patch, MagicMock

# Adjust search path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.incident import create_incident, _ACTIVE_INCIDENTS
from app.evidence import EvidencePackage, CollectorResult
from app.collector import CollectorManager
from app.serializer import (
    serialize_incident,
    serialize_evidence_package,
    serialize_collector_result
)
from app.storage import save_incident_payload, INCIDENTS_DIR

def run_persistence_tests():
    print("==================================================")
    print("Starting Type 1 Verification")
    print("==================================================")
    
    # Track status
    results = {
        "Serializer": False,
        "Storage": False,
        "Integration": False,
        "Failure Handling": False,
        "JSON Validation": False,
        "Regression": False
    }

    # Clean up incidents folder before starting test run to ensure a clean state
    if os.path.exists(INCIDENTS_DIR):
        shutil.rmtree(INCIDENTS_DIR)

    # 1. Serializer Tests
    try:
        # Create a mock collector result
        res1 = CollectorResult(
            collector_name="mock1",
            success=True,
            started_at="2026-07-14 12:00:00",
            finished_at="2026-07-14 12:00:01",
            duration_ms=100.5,
            data={"val": "üñîçødé"},
            error=None
        )
        res2 = CollectorResult(
            collector_name="mock2",
            success=False,
            started_at="2026-07-14 12:00:01",
            finished_at="2026-07-14 12:00:02",
            duration_ms=200.5,
            data=None,
            error="Mock error"
        )
        
        # Test individual serializers
        d_res1 = serialize_collector_result(res1)
        assert isinstance(d_res1, dict)
        assert d_res1["collector_name"] == "mock1"
        
        pkg = EvidencePackage(
            incident_id="INC-TEST-0001",
            target_name="Test Target",
            collected_at="2026-07-14 12:00:02",
            collector_results=[res1, res2]
        )
        
        d_pkg = serialize_evidence_package(pkg)
        assert isinstance(d_pkg, dict)
        assert d_pkg["collector_results"][0]["collector_name"] == "mock1"
        assert d_pkg["collector_results"][1]["collector_name"] == "mock2"
        # Verify order is preserved
        assert [r["collector_name"] for r in d_pkg["collector_results"]] == ["mock1", "mock2"]
        
        # Mock incident
        mock_inc = MagicMock()
        mock_inc.id = "INC-TEST-0001"
        mock_inc.target_name = "Test Target"
        mock_inc.started_at = "2026-07-14 12:00:00"
        mock_inc.status = "ACTIVE"
        mock_inc.failure_reason = "HTTP failure"
        mock_inc.verification_attempts = 2
        mock_inc.evidence = pkg
        
        d_inc = serialize_incident(mock_inc)
        assert isinstance(d_inc, dict)
        assert d_inc["metadata"]["schema_version"] == 1
        assert "persisted_at" in d_inc["metadata"]
        assert d_inc["metadata"]["total_collectors_executed"] == 2
        assert d_inc["metadata"]["total_collectors_succeeded"] == 1
        assert d_inc["metadata"]["total_collectors_failed"] == 1
        assert d_inc["metadata"]["total_collection_duration_ms"] == 301.0
        
        # Test empty evidence package serialization
        mock_inc_empty = MagicMock()
        mock_inc_empty.id = "INC-TEST-EMPTY"
        mock_inc_empty.evidence = None
        d_empty = serialize_incident(mock_inc_empty)
        assert d_empty["metadata"]["total_collectors_executed"] == 0
        assert d_empty["metadata"]["total_collection_duration_ms"] == 0.0
        
        results["Serializer"] = True
    except Exception as e:
        print(f"Serializer Tests FAILED: {e}")

    # 2. Storage Tests
    try:
        test_payload = {
            "incident_id": "INC-TEST-0001",
            "content": "üñîçødé test"
        }
        
        save_success = save_incident_payload("INC-TEST-0001", test_payload)
        assert save_success is True
        
        # Check folder and file creation
        folder_path = os.path.join(INCIDENTS_DIR, "INC-TEST-0001")
        assert os.path.exists(folder_path)
        
        file_path = os.path.join(folder_path, "incident.json")
        assert os.path.exists(file_path)
        # Ensure tmp file is deleted
        assert not os.path.exists(os.path.join(folder_path, "incident.json.tmp"))
        
        # Load file and assert formatting and encoding
        with open(file_path, "r", encoding="utf-8") as f:
            raw_content = f.read()
            # Confirm pretty print spacing (indent=2)
            assert "  \"incident_id\":" in raw_content
            
            # Confirm JSON is valid and loadable
            loaded = json.loads(raw_content)
            assert loaded["content"] == "üñîçødé test"
            
        results["Storage"] = True
    except Exception as e:
        print(f"Storage Tests FAILED: {e}")

    # 3. Incident Integration Tests
    try:
        config = {
            "collectors": {
                "nginx": {"enabled": False},
                "cloudflared": {"enabled": False},
                "uvicorn": {"enabled": False},
                "postgres": {"enabled": False},
                "redis": {"enabled": False},
                "system": {"enabled": False},
                "launchctl": {"enabled": False}
            }
        }
        
        # Clear in-memory incidents first
        _ACTIVE_INCIDENTS.clear()
        
        # Trigger create_incident
        inc = create_incident("Integration_Test_Target", "Check Failed", 2, config)
        
        assert inc is not None
        assert inc.target_name == "Integration_Test_Target"
        
        # Verify in-memory persistence
        assert "Integration_Test_Target" in _ACTIVE_INCIDENTS
        assert _ACTIVE_INCIDENTS["Integration_Test_Target"] == inc
        
        # Verify filesystem folder exists for this incident ID
        inc_dir = os.path.join(INCIDENTS_DIR, inc.id)
        assert os.path.exists(inc_dir)
        assert os.path.exists(os.path.join(inc_dir, "incident.json"))
        
        results["Integration"] = True
    except Exception as e:
        print(f"Integration Tests FAILED: {e}")

    # 4. Failure Tests
    try:
        # Scenario A: Storage failure (should not leak exceptions, incident remains in memory)
        _ACTIVE_INCIDENTS.clear()
        with patch("app.storage.save_incident_payload", side_effect=Exception("Disk full simulated")):
            inc = create_incident("Storage_Fail_Target", "Check Failed", 2, config)
            assert inc is not None
            assert "Storage_Fail_Target" in _ACTIVE_INCIDENTS
            
        # Scenario B: Serializer failure (should not leak exceptions, incident remains in memory)
        _ACTIVE_INCIDENTS.clear()
        with patch("app.serializer.serialize_incident", side_effect=Exception("Serializing crash simulation")):
            inc = create_incident("Serializer_Fail_Target", "Check Failed", 2, config)
            assert inc is not None
            assert "Serializer_Fail_Target" in _ACTIVE_INCIDENTS
            
        results["Failure Handling"] = True
    except Exception as e:
        print(f"Failure Handling Tests FAILED: {e}")

    # 5. JSON Validation Tests
    try:
        _ACTIVE_INCIDENTS.clear()
        inc = create_incident("JSON_Validation_Target", "HTTP status code 500", 2, config)
        
        file_path = os.path.join(INCIDENTS_DIR, inc.id, "incident.json")
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        assert data["incident_id"] == inc.id
        assert data["target_name"] == "JSON_Validation_Target"
        assert data["status"] == "ACTIVE"
        assert data["failure_reason"] == "HTTP status code 500"
        assert "evidence" in data
        assert "metadata" in data
        
        meta = data["metadata"]
        assert meta["schema_version"] == 1
        assert "persisted_at" in meta
        assert meta["total_collectors_executed"] == 0
        assert meta["total_collectors_succeeded"] == 0
        assert meta["total_collectors_failed"] == 0
        assert meta["total_collection_duration_ms"] == 0.0
        
        results["JSON Validation"] = True
    except Exception as e:
        print(f"JSON Validation Tests FAILED: {e}")

    # 6. Regression Tests
    try:
        # Verify CollectorManager is intact and registry functions work
        assert len(CollectorManager._registry) >= 7
        print("CollectorManager registry intact: OK")
        
        results["Regression"] = True
    except Exception as e:
        print(f"Regression Tests FAILED: {e}")

    # Clean up test output folders at the end
    if os.path.exists(INCIDENTS_DIR):
        shutil.rmtree(INCIDENTS_DIR)

    # Print summary
    print("\n--------------------------------------------------")
    for test_name, passed in results.items():
        dots = "." * (25 - len(test_name))
        status = "PASSED" if passed else "FAILED"
        print(f"{test_name} {dots} {status}")
    print("--------------------------------------------------")
    
    all_passed = all(results.values())
    if all_passed:
        print("\n==================================================")
        print("ALL TESTS PASSED")
        print("TYPE 1 VERIFIED")
        print("==================================================")
    else:
        print("\n==================================================")
        print("SOME TESTS FAILED")
        print("==================================================")

if __name__ == "__main__":
    run_persistence_tests()
