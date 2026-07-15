import sys
import os
import yaml
from unittest.mock import patch, MagicMock
import urllib.error

# Adjust search path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import load_config
from app.notification import Notification, NotificationType, NotificationStatus
from app.notifier.telegram import TelegramProvider

class MockHTTPResponse:
    def __init__(self, status: int, data: str):
        self.status = status
        self.data = data.encode("utf-8")
    def read(self) -> bytes:
        return self.data
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

def test_config_validation():
    print("Configuration Validation ..... ", end="", flush=True)
    
    base_config = {
        "targets": [{"name": "T", "endpoint": "http://a", "interval": 10}],
        "incident": {"verification_attempts": 1, "verification_delay": 1},
        "collectors": {},
        "notifier": {
            "telegram": {
                "enabled": True,
                "bot_token": "12345:token",
                "chat_id": "67890",
                "timeout": 5
            }
        }
    }
    
    def write_temp_config(notifier_cfg):
        cfg = dict(base_config)
        cfg["notifier"] = notifier_cfg
        os.makedirs("config", exist_ok=True)
        with open("config/temp_notifier_config.yaml", "w") as f:
            yaml.dump(cfg, f)

    try:
        # 1. Valid Configuration
        write_temp_config({
            "telegram": {
                "enabled": True,
                "bot_token": "12345:token",
                "chat_id": "67890",
                "timeout": 10
            }
        })
        parsed = load_config("config/temp_notifier_config.yaml")
        assert parsed["notifier"]["telegram"]["enabled"] is True
        assert parsed["notifier"]["telegram"]["timeout"] == 10
        
        # Helper to assert configuration fails
        def assert_validation_fails(notifier_cfg):
            write_temp_config(notifier_cfg)
            try:
                with patch("sys.exit") as mock_exit:
                    load_config("config/temp_notifier_config.yaml")
                    assert mock_exit.called
            except SystemExit:
                pass

        # 2. Empty bot token when enabled
        assert_validation_fails({
            "telegram": {"enabled": True, "bot_token": "", "chat_id": "123", "timeout": 5}
        })

        # 3. Empty chat id when enabled
        assert_validation_fails({
            "telegram": {"enabled": True, "bot_token": "123", "chat_id": "", "timeout": 5}
        })

        # 4. Timeout <= 0
        assert_validation_fails({
            "telegram": {"enabled": True, "bot_token": "123", "chat_id": "456", "timeout": 0}
        })
        assert_validation_fails({
            "telegram": {"enabled": True, "bot_token": "123", "chat_id": "456", "timeout": -5}
        })

        # 5. Invalid type for enabled
        assert_validation_fails({
            "telegram": {"enabled": "yes", "bot_token": "123", "chat_id": "456", "timeout": 5}
        })

        # 6. Invalid structure (not dict)
        try:
            write_temp_config({"telegram": "should_be_dict"})
            with patch("sys.exit") as mock_exit:
                load_config("config/temp_notifier_config.yaml")
                assert mock_exit.called
        except SystemExit:
            pass

        print("PASSED")
    finally:
        if os.path.exists("config/temp_notifier_config.yaml"):
            os.remove("config/temp_notifier_config.yaml")

def test_telegram_provider():
    # 1. Message formatting verification
    print("Message Formatting ........... ", end="", flush=True)
    provider = TelegramProvider(bot_token="token", chat_id="123", timeout=5)
    
    n_created = Notification(
        notification_type=NotificationType.INCIDENT_CREATED,
        incident_id="INC-001",
        target_name="TestTarget",
        status=NotificationStatus.PENDING,
        created_at="2026-07-15 10:00:00",
        message="Failure reason"
    )
    
    msg_created = provider._build_message(n_created)
    assert "HexaBlackBox\n\nIncident Created" in msg_created
    assert "Incident ID: INC-001" in msg_created
    assert "Target: TestTarget" in msg_created
    assert "Started At: 2026-07-15 10:00:00" in msg_created
    assert "Status: ACTIVE" in msg_created
    
    n_resolved = Notification(
        notification_type=NotificationType.INCIDENT_RESOLVED,
        incident_id="INC-002",
        target_name="TestTarget",
        status=NotificationStatus.PENDING,
        created_at="2026-07-15 10:05:00",
        message="Resolved reason",
        metadata={"resolved_at": "2026-07-15 10:05:00", "duration_seconds": 300}
    )
    msg_resolved = provider._build_message(n_resolved)
    assert "HexaBlackBox\n\nIncident Resolved" in msg_resolved
    assert "Incident ID: INC-002" in msg_resolved
    assert "Target: TestTarget" in msg_resolved
    assert "Recovered At: 2026-07-15 10:05:00" in msg_resolved
    assert "Duration: 300 seconds" in msg_resolved
    assert "Status: RESOLVED" in msg_resolved
    
    print("PASSED")

    # 2. HTTP Dispatch Scenarios
    # Scenario A: HTTP 200, ok=True
    print("Scenario A (HTTP 200, ok=True) .. ", end="", flush=True)
    with patch("urllib.request.urlopen", return_value=MockHTTPResponse(200, '{"ok": true}')):
        assert provider.send(n_created) is True
    print("PASSED")

    # Scenario B: HTTP 200, ok=False
    print("Scenario B (HTTP 200, ok=False) . ", end="", flush=True)
    with patch("urllib.request.urlopen", return_value=MockHTTPResponse(200, '{"ok": false}')):
        assert provider.send(n_created) is False
    print("PASSED")

    # Scenario C: HTTP 400 Bad Request
    print("Scenario C (HTTP 400 Failure) .. ", end="", flush=True)
    with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError("url", 400, "Bad Request", None, None)):
        assert provider.send(n_created) is False
    print("PASSED")

    # Scenario D: Timeout/Network Error
    print("Scenario D (Network Timeout) ... ", end="", flush=True)
    with patch("urllib.request.urlopen", side_effect=TimeoutError("Connection timed out")):
        assert provider.send(n_created) is False
    print("PASSED")

def test_regression():
    print("Regression ................... ", end="", flush=True)
    # Check that core collectors load validation behaves as expected
    parsed = load_config("config/config.yaml")
    assert parsed is not None
    assert "targets" in parsed
    print("PASSED")

def main():
    print("==================================================")
    print("Starting Type 1 Verification")
    print("==================================================")
    try:
        test_config_validation()
        test_telegram_provider()
        test_regression()
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
