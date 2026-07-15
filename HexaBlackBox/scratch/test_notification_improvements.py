import sys
import os
import yaml
from socket import gethostname
from unittest.mock import patch, MagicMock

# Adjust search path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import load_config
from app.notification import Notification, NotificationType, NotificationStatus
from app.notifier import NotificationManager, NotificationProvider
from app.notifier.telegram import TelegramProvider
from app.incident import create_incident, resolve_incident, _get_hostname_safely

class DummyProvider(NotificationProvider):
    def __init__(self):
        self.send_mock = MagicMock(return_value=True)
    def send(self, notification):
        return self.send_mock(notification)

def test_config_suppression_validation():
    print("Deduplication Config Validation ..... ", end="", flush=True)
    
    base_config = {
        "targets": [{"name": "T", "endpoint": "http://a", "interval": 10}],
        "incident": {"verification_attempts": 1, "verification_delay": 1},
        "collectors": {},
        "notifier": {
            "suppression_enabled": True
        }
    }
    
    def write_temp_config(suppression_val):
        cfg = dict(base_config)
        cfg["notifier"] = {"suppression_enabled": suppression_val}
        os.makedirs("config", exist_ok=True)
        with open("config/temp_suppression_config.yaml", "w") as f:
            yaml.dump(cfg, f)

    try:
        # 1. Valid True
        write_temp_config(True)
        parsed = load_config("config/temp_suppression_config.yaml")
        assert parsed["notifier"]["suppression_enabled"] is True
        
        # 2. Valid False
        write_temp_config(False)
        parsed = load_config("config/temp_suppression_config.yaml")
        assert parsed["notifier"]["suppression_enabled"] is False

        # 3. Invalid Type (should fail validation and exit)
        write_temp_config("not_a_bool")
        try:
            with patch("sys.exit") as mock_exit:
                load_config("config/temp_suppression_config.yaml")
                assert mock_exit.called
        except SystemExit:
            pass

        print("PASSED")
    finally:
        if os.path.exists("config/temp_suppression_config.yaml"):
            os.remove("config/temp_suppression_config.yaml")

def test_bounded_suppression_registry():
    print("Bounded Deduplication Registry ....... ", end="", flush=True)
    
    manager = NotificationManager(suppression_enabled=True)
    provider = DummyProvider()
    manager.register_provider(provider)
    
    n_created = Notification(
        notification_type=NotificationType.INCIDENT_CREATED,
        incident_id="INC-B3-0001",
        target_name="TestTarget",
        status=NotificationStatus.PENDING,
        created_at="2026-07-15 12:00:00",
        message="Created Alert"
    )
    
    n_resolved = Notification(
        notification_type=NotificationType.INCIDENT_RESOLVED,
        incident_id="INC-B3-0001",
        target_name="TestTarget",
        status=NotificationStatus.PENDING,
        created_at="2026-07-15 12:05:00",
        message="Resolved Alert",
        metadata={"resolved_at": "2026-07-15 12:05:00", "duration_seconds": 300}
    )
    
    # First creation alert should dispatch
    assert manager.notify(n_created) is True
    # Second creation alert should be suppressed (returns True no-op)
    assert manager.notify(n_created) is True
    
    # Assert provider was only called once for creation
    assert provider.send_mock.call_count == 1
    
    # Resolve alert should dispatch
    assert manager.notify(n_resolved) is True
    # Second resolve alert should be suppressed
    assert manager.notify(n_resolved) is True
    
    # Bounded Cleanup Check:
    # Resolve 101 other alerts for different incident IDs to trigger bounded sliding queue eviction
    for idx in range(2, 103):
        n_other = Notification(
            notification_type=NotificationType.INCIDENT_RESOLVED,
            incident_id=f"INC-B3-{idx:04d}",
            target_name="TestTarget",
            status=NotificationStatus.PENDING,
            created_at="2026-07-15 12:05:00",
            message="Resolved Alert",
            metadata={"resolved_at": "2026-07-15 12:05:00", "duration_seconds": 300}
        )
        manager.notify(n_other)
        
    created_key = f"{n_created.incident_id}:{n_created.notification_type.value}"
    resolved_key = f"{n_resolved.incident_id}:{n_resolved.notification_type.value}"
    assert created_key not in manager._dispatched_alerts
    assert resolved_key not in manager._dispatched_alerts
    
    print("PASSED")

def test_resilient_hostname_lookup():
    print("Resilient Hostname Retrieval ........ ", end="", flush=True)
    
    # 1. Standard retrieval matches local hostname
    assert _get_hostname_safely() == gethostname()
    
    # 2. Resilient fallback if socket.gethostname fails
    with patch("socket.gethostname", side_effect=RuntimeError("DNS socket failure")):
        assert _get_hostname_safely() == "Unknown"
        
    print("PASSED")

def test_rich_message_template():
    print("Rich Alert Message Formatting ....... ", end="", flush=True)
    
    provider = TelegramProvider(bot_token="token", chat_id="123", timeout=5)
    
    n = Notification(
        notification_type=NotificationType.INCIDENT_CREATED,
        incident_id="INC-B3-0002",
        target_name="MyTestTarget",
        status=NotificationStatus.PENDING,
        created_at="2026-07-15T12:00:00Z",
        message="Alert Created",
        metadata={
            "endpoint": "http://my-endpoint:8000/health",
            "failure_reason": "HTTP status code 503",
            "incident_dir": "incidents/INC-B3-0002",
            "incident_json": "incidents/INC-B3-0002/incident.json",
            "evidence_package": "available",
            "host": "test-runner-node"
        }
    )
    
    msg = provider._build_message(n)
    
    # Assert headers and rich keys
    assert "HexaBlackBox\n\nIncident Created" in msg
    assert "Incident ID: INC-B3-0002" in msg
    assert "Target: MyTestTarget" in msg
    assert "Host: test-runner-node" in msg
    assert "Endpoint: http://my-endpoint:8000/health" in msg
    assert "Started At: 2026-07-15T12:00:00Z" in msg
    assert "Status: ACTIVE" in msg
    assert "Failure: HTTP 503 Service Unavailable" in msg
    
    # Developer Guidance checks
    assert "Developer Guidance" in msg
    assert "Incident Folder\nincidents/INC-B3-0002/" in msg
    assert "Incident Package\nincidents/INC-B3-0002/incident.json" in msg
    assert "Collector diagnostics included." in msg
    
    print("PASSED")

def test_endpoint_metadata_passing():
    print("Endpoint Metadata Forwarding ........ ", end="", flush=True)
    
    config = {
        "targets": [{"name": "API", "endpoint": "http://api/health", "interval": 10}],
        "incident": {"verification_attempts": 1, "verification_delay": 1},
        "collectors": {}
    }
    
    notifier = NotificationManager(suppression_enabled=False)
    provider = DummyProvider()
    notifier.register_provider(provider)
    
    # Create incident with explicit endpoint parameter
    inc = create_incident(
        target_name="API",
        failure_reason="Timeout Error",
        verification_attempts=1,
        config=config,
        notifier=notifier,
        endpoint="http://api/health"
    )
    
    # Verify provider received notification with endpoint in metadata
    assert provider.send_mock.call_count == 1
    sent_notification = provider.send_mock.call_args[0][0]
    assert sent_notification.metadata["endpoint"] == "http://api/health"
    assert sent_notification.metadata["host"] == _get_hostname_safely()
    
    print("PASSED")

def main():
    print("==================================================")
    print("Starting Type 1 Verification (Batch 3)")
    print("==================================================")
    try:
        test_config_suppression_validation()
        test_bounded_suppression_registry()
        test_resilient_hostname_lookup()
        test_rich_message_template()
        test_endpoint_metadata_passing()
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
