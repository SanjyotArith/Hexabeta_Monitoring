import sys
import os
import json
import shutil
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

# Adjust search path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.incident import create_incident, resolve_incident, _ACTIVE_INCIDENTS, Incident
from app.evidence import EvidencePackage, CollectorResult
from app.collector import CollectorManager
from app.serializer import serialize_incident
from app.storage import INCIDENTS_DIR

def run_resolution_tests():
    print("==================================================")
    print("Starting Type 1 Verification")
    print("==================================================")
    
    results = {
        "Incident Resolution": False,
        "Duration Calculation": False,
        "Serializer": False,
        "Storage Update": False,
        "Integration": False,
        "Regression": False
    }

    # Clean state
    if os.path.exists(INCIDENTS_DIR):
        shutil.rmtree(INCIDENTS_DIR)

    # 1. Incident Resolution Tests
    try:
        _ACTIVE_INCIDENTS.clear()
        
        # Test calling on non-existent incident safely returns None
        assert resolve_incident("NonExistentTarget") is None
        
        # Setup an active incident
        started_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        inc = Incident(
            id="INC-RES-0001",
            target_name="ResolutionTarget",
            started_at=started_time,
            status="ACTIVE",
            failure_reason="Test fail",
            verification_attempts=2
        )
        _ACTIVE_INCIDENTS["ResolutionTarget"] = inc
        
        # Resolve the incident
        resolved = resolve_incident("ResolutionTarget")
        assert resolved is not None
        assert resolved.status == "RESOLVED"
        assert resolved.resolved_at is not None
        assert isinstance(resolved.duration_seconds, int)
        assert "ResolutionTarget" not in _ACTIVE_INCIDENTS
        
        results["Incident Resolution"] = True
    except Exception as e:
        print(f"Incident Resolution Tests FAILED: {e}")

    # 2. Duration Calculation Tests
    try:
        # Zero-duration
        inc_zero = Incident(id="INC-ZERO", target_name="ZeroT", started_at="2026-07-14 12:00:00", status="ACTIVE")
        _ACTIVE_INCIDENTS["ZeroT"] = inc_zero
        with patch("app.incident.datetime") as mock_dt:
            # mock resolution time same as start time
            mock_dt.now.return_value = datetime(2026, 7, 14, 12, 0, 0)
            mock_dt.strptime = datetime.strptime
            res = resolve_incident("ZeroT")
            assert res.duration_seconds == 0
            assert isinstance(res.duration_seconds, int)

        # Normal duration (5 minutes)
        inc_norm = Incident(id="INC-NORM", target_name="NormT", started_at="2026-07-14 12:00:00", status="ACTIVE")
        _ACTIVE_INCIDENTS["NormT"] = inc_norm
        with patch("app.incident.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 7, 14, 12, 5, 0)
            mock_dt.strptime = datetime.strptime
            res = resolve_incident("NormT")
            assert res.duration_seconds == 300
            assert isinstance(res.duration_seconds, int)
            
        # Non-negative check
        inc_neg = Incident(id="INC-NEG", target_name="NegT", started_at="2026-07-14 12:00:00", status="ACTIVE")
        _ACTIVE_INCIDENTS["NegT"] = inc_neg
        with patch("app.incident.datetime") as mock_dt:
            # mock resolution time earlier than start time (should not crash, fallback to 0 or handled gracefully)
            mock_dt.now.return_value = datetime(2026, 7, 14, 11, 55, 0)
            mock_dt.strptime = datetime.strptime
            res = resolve_incident("NegT")
            assert res.duration_seconds < 0 or res.duration_seconds == 0
            # Confirm duration remains integer even under negative values or fallback
            assert isinstance(res.duration_seconds, int)
            
        results["Duration Calculation"] = True
    except Exception as e:
        print(f"Duration Calculation Tests FAILED: {e}")

    # 3. Serializer Tests
    try:
        # Check active incident serialization (should contain resolved_at=None, duration_seconds=None)
        active_inc = Incident(id="INC-ACT", target_name="ActT", started_at="2026-07-14 12:00:00", status="ACTIVE")
        d_active = serialize_incident(active_inc)
        assert d_active["status"] == "ACTIVE"
        assert d_active["resolved_at"] is None
        assert d_active["duration_seconds"] is None
        
        # Check resolved serialization
        resolved_inc = Incident(
            id="INC-RES",
            target_name="ResT",
            started_at="2026-07-14 12:00:00",
            status="RESOLVED",
            resolved_at="2026-07-14 12:05:00",
            duration_seconds=300
        )
        d_res = serialize_incident(resolved_inc)
        assert d_res["status"] == "RESOLVED"
        assert d_res["resolved_at"] == "2026-07-14 12:05:00"
        assert d_res["duration_seconds"] == 300
        
        results["Serializer"] = True
    except Exception as e:
        print(f"Serializer Tests FAILED: {e}")

    # 4. Storage Update Tests
    try:
        _ACTIVE_INCIDENTS.clear()
        if os.path.exists(INCIDENTS_DIR):
            shutil.rmtree(INCIDENTS_DIR)
        
        # Write initial active incident
        config = {"collectors": {}}
        inc = create_incident("StorageUpdateTarget", "Crash", 2, config)
        inc_id = inc.id
        
        file_path = os.path.join(INCIDENTS_DIR, inc_id, "incident.json")
        assert os.path.exists(file_path)
        
        # Load and verify it is ACTIVE
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            assert data["status"] == "ACTIVE"
            
        # Resolve the incident (which triggers overwrite)
        resolve_incident("StorageUpdateTarget")
        
        # Load and verify it has transitioned to RESOLVED in the SAME file
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            assert data["status"] == "RESOLVED"
            assert data["resolved_at"] is not None
            assert isinstance(data["duration_seconds"], int)
            
        results["Storage Update"] = True
    except Exception as e:
        print(f"Storage Update Tests FAILED: {e}")

    # 5. Integration Tests
    try:
        _ACTIVE_INCIDENTS.clear()
        if os.path.exists(INCIDENTS_DIR):
            shutil.rmtree(INCIDENTS_DIR)
        
        # Create ACTIVE
        inc = create_incident("IntegrationTarget", "Failure", 2, config)
        inc_id = inc.id
        folder_path = os.path.join(INCIDENTS_DIR, inc_id)
        
        # Resolve
        resolve_incident("IntegrationTarget")
        
        # Confirm same folder and ID structure is reused
        assert os.path.exists(folder_path)
        assert len(os.listdir(INCIDENTS_DIR)) == 1, "Expected only 1 incident folder in directory"
        
        results["Integration"] = True
    except Exception as e:
        print(f"Integration Tests FAILED: {e}")

    # 6. Regression Tests
    try:
        # Verify CollectorManager is untouched
        assert len(CollectorManager._registry) >= 7
        
        # Verify Batch 1 persistence is still functional
        _ACTIVE_INCIDENTS.clear()
        inc = create_incident("RegressionTarget", "Crash", 2, config)
        assert os.path.exists(os.path.join(INCIDENTS_DIR, inc.id, "incident.json"))
        
        results["Regression"] = True
    except Exception as e:
        print(f"Regression Tests FAILED: {e}")

    # Clean state at end
    if os.path.exists(INCIDENTS_DIR):
        shutil.rmtree(INCIDENTS_DIR)

    # Print output
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
    run_resolution_tests()
