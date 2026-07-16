import sys
import os
from datetime import datetime, timezone
import time
from unittest.mock import patch, MagicMock

# Adjust search path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.health import RuntimeHealthManager, ComponentHealth
from app.monitor import start_monitoring

def test_component_registration_and_initial_state():
    print("Component Registration & Initial State ... ", end="", flush=True)
    manager = RuntimeHealthManager()
    
    # Check registration
    manager.register_component("test_comp")
    health = manager.get_health("test_comp")
    
    assert health is not None
    assert health.name == "test_comp"
    assert health.status == "HEALTHY"
    assert health.last_heartbeat is None
    assert health.last_success is None
    assert health.last_failure is None
    assert health.failure_reason is None
    assert health.consecutive_failures == 0
    
    # Duplicate registration should not overwrite existing state
    manager.heartbeat("test_comp")
    first_hb = manager.get_health("test_comp").last_heartbeat
    assert first_hb is not None
    
    manager.register_component("test_comp")
    assert manager.get_health("test_comp").last_heartbeat == first_hb
    
    print("PASSED")

def test_heartbeat_updates():
    print("Heartbeat Updates ........................ ", end="", flush=True)
    manager = RuntimeHealthManager()
    manager.register_component("test_comp")
    
    manager.heartbeat("test_comp")
    health = manager.get_health("test_comp")
    
    assert isinstance(health.last_heartbeat, datetime)
    assert health.last_success is None
    assert health.last_failure is None
    assert health.failure_reason is None
    assert health.consecutive_failures == 0
    
    print("PASSED")

def test_success_execution():
    print("Successful Execution Updates ............ ", end="", flush=True)
    manager = RuntimeHealthManager()
    manager.register_component("test_comp")
    
    # Put into a failed state first to verify reset behavior
    manager.mark_failure("test_comp", "API timeout")
    assert manager.get_health("test_comp").consecutive_failures == 1
    
    manager.heartbeat("test_comp")
    manager.mark_success("test_comp")
    
    health = manager.get_health("test_comp")
    assert health.status == "HEALTHY"
    assert isinstance(health.last_success, datetime)
    assert health.consecutive_failures == 0
    assert health.failure_reason is None
    
    print("PASSED")

def test_failure_execution():
    print("Failed Execution Updates ................ ", end="", flush=True)
    manager = RuntimeHealthManager()
    manager.register_component("test_comp")
    
    manager.heartbeat("test_comp")
    manager.mark_failure("test_comp", "HTTP status code 500")
    
    health = manager.get_health("test_comp")
    assert health.status == "UNHEALTHY"
    assert isinstance(health.last_failure, datetime)
    assert health.failure_reason == "HTTP status code 500"
    assert health.consecutive_failures == 1
    
    # Consecutive count increment
    manager.mark_failure("test_comp", "HTTP status code 502")
    health2 = manager.get_health("test_comp")
    assert health2.consecutive_failures == 2
    assert health2.failure_reason == "HTTP status code 502"
    
    print("PASSED")

def test_defensive_copying():
    print("Defensive Copying Check .................. ", end="", flush=True)
    manager = RuntimeHealthManager()
    manager.register_component("test_comp")
    
    health = manager.get_health("test_comp")
    # Mutate retrieved object externally
    health.status = "MUTATED"
    health.consecutive_failures = 999
    
    # Manager's internal state must remain intact
    internal_health = manager.get_health("test_comp")
    assert internal_health.status == "HEALTHY"
    assert internal_health.consecutive_failures == 0
    
    print("PASSED")

def test_monitoring_loop_integration():
    print("Monitoring Loop Integration ............. ", end="", flush=True)
    
    config = {
        "targets": [{"name": "API", "endpoint": "http://api", "interval": 1}],
        "incident": {"verification_attempts": 1, "verification_delay": 1},
        "collectors": {}
    }
    
    health_manager = RuntimeHealthManager()
    health_manager.register_component("monitoring_loop")
    
    # Mock checks to prevent blocking and verify exception propagation
    with patch("app.monitor.execute_check") as mock_check:
        mock_check.return_value = MagicMock(status="HEALTHY", reason=None)
        
        class EndCycleException(BaseException):
            pass
            
        sleep_count = 0
        def safe_sleep_side_effect(duration):
            nonlocal sleep_count
            sleep_count += 1
            if sleep_count > 1:
                raise EndCycleException("End of cycle")
            
        with patch("time.sleep", side_effect=safe_sleep_side_effect):
            try:
                start_monitoring(config, health_manager=health_manager)
            except EndCycleException:
                pass
                
        # Assert health manager was updated with success
        health = health_manager.get_health("monitoring_loop")
        assert health.status == "HEALTHY"
        assert isinstance(health.last_heartbeat, datetime)
        assert isinstance(health.last_success, datetime)
        assert health.consecutive_failures == 0
        
        # Test exception propagation and failure marking
        mock_check.side_effect = RuntimeError("Socket timeout")
        try:
            start_monitoring(config, health_manager=health_manager)
            raise AssertionError("Exception was suppressed!")
        except RuntimeError:
            # Exception was successfully propagated (original behavior preserved)
            pass
            
        # Assert health manager recorded failure
        health_fail = health_manager.get_health("monitoring_loop")
        assert health_fail.status == "UNHEALTHY"
        assert isinstance(health_fail.last_failure, datetime)
        assert health_fail.failure_reason == "Socket timeout"
        assert health_fail.consecutive_failures == 1

    print("PASSED")

def test_datetime_validation():
    print("Datetime Object Validation .............. ", end="", flush=True)
    manager = RuntimeHealthManager()
    manager.register_component("test_comp")
    
    manager.heartbeat("test_comp")
    manager.mark_success("test_comp")
    manager.mark_failure("test_comp", "error")
    
    health = manager.get_health("test_comp")
    assert isinstance(health.last_heartbeat, datetime)
    assert isinstance(health.last_success, datetime)
    assert isinstance(health.last_failure, datetime)
    
    print("PASSED")

def main():
    print("==================================================")
    print("Starting Type 1 Verification (Milestone 8 - Batch 1)")
    print("==================================================")
    try:
        test_component_registration_and_initial_state()
        test_heartbeat_updates()
        test_success_execution()
        test_failure_execution()
        test_defensive_copying()
        test_monitoring_loop_integration()
        test_datetime_validation()
        print("\n==================================================")
        print("ALL TESTS PASSED")
        print("TYPE 1 VERIFIED")
        print("==================================================")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print("\n==================================================")
        print("SOME TESTS FAILED")
        print("==================================================")

if __name__ == "__main__":
    main()
