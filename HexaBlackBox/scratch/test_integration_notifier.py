import sys
import os
import shutil
import time
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

# Adjust search path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import load_config
from app.notification import Notification, NotificationType, NotificationStatus
from app.notifier import NotificationManager
from app.notifier.telegram import TelegramProvider
from app.incident import create_incident, resolve_incident, _ACTIVE_INCIDENTS, _DAILY_COUNTERS
from app.monitor import start_monitoring

# Mock HTTP response to log messages dispatched
sent_telegram_messages = []

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

def mock_urlopen(req, timeout=5):
    import json
    data = req.data.decode("utf-8")
    payload = json.loads(data)
    sent_telegram_messages.append(payload["text"])
    return MockHTTPResponse(200, '{"ok": true}')

def run_type2_integration():
    print("==================================================")
    print("Starting Type 2 End-to-End Integration Verification")
    print("==================================================")
    
    # Clean active incident mappings
    _ACTIVE_INCIDENTS.clear()
    _DAILY_COUNTERS.clear()
    
    config = {
        "targets": [{"name": "HexaBeta Backend API", "endpoint": "http://localhost:8002/api/health", "interval": 1}],
        "incident": {"verification_attempts": 1, "verification_delay": 1},
        "collectors": {},
        "notifier": {
            "suppression_enabled": True,
            "telegram": {
                "enabled": True,
                "bot_token": "mock_token_123",
                "chat_id": "mock_chat_456",
                "timeout": 5
            }
        }
    }
    
    # 1. Instantiate explicit NotificationManager and TelegramProvider
    notifier = NotificationManager(suppression_enabled=True)
    telegram_provider = TelegramProvider(
        bot_token="mock_token_123",
        chat_id="mock_chat_456",
        timeout=5
    )
    notifier.register_provider(telegram_provider)
    
    # Patch urlopen to capture outbound Telegram messages
    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        
        # Scenario 1: Transition from HEALTHY to UNHEALTHY (Incident Created)
        print("\n[Step 1] Triggering incident creation...")
        incident = create_incident(
            target_name="HexaBeta Backend API",
            failure_reason="HTTP status code 503",
            verification_attempts=2,
            config=config,
            notifier=notifier,
            endpoint="http://localhost:8002/api/health"
        )
        
        print("\n--- Outbound Telegram Alert Created Message ---")
        print(sent_telegram_messages[-1])
        print("-----------------------------------------------\n")
        
        # Verify message integrity contains all target fields
        created_msg = sent_telegram_messages[-1]
        assert "Incident Created" in created_msg
        assert "Incident ID: INC-" in created_msg
        assert "Target: HexaBeta Backend API" in created_msg
        assert "Endpoint: http://localhost:8002/api/health" in created_msg
        assert "Status: ACTIVE" in created_msg
        assert "Failure: HTTP 503 Service Unavailable" in created_msg
        assert "Developer Guidance" in created_msg
        assert f"Incident Folder\nincidents/{incident.id}/" in created_msg
        assert f"Incident Package\nincidents/{incident.id}/incident.json" in created_msg
        
        # Verify the actual directory exists on disk
        incident_dir = os.path.join("incidents", incident.id)
        incident_json_path = os.path.join(incident_dir, "incident.json")
        assert os.path.isdir(incident_dir), f"Directory {incident_dir} not found on disk"
        assert os.path.isfile(incident_json_path), f"File {incident_json_path} not found on disk"
        print(f"Verified incident payload written to disk at: {incident_json_path}")
        
        # Scenario 2: Deduplication Suppression while ACTIVE
        print("\n[Step 2] Attempting duplicate creation alert dispatch...")
        initial_count = len(sent_telegram_messages)
        # Call notifier.notify with the same notification type again
        from app.notification import NotificationType, NotificationStatus
        dup_notification = Notification(
            notification_type=NotificationType.INCIDENT_CREATED,
            incident_id=incident.id,
            target_name="HexaBeta Backend API",
            status=NotificationStatus.PENDING,
            created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            message="Duplicate attempt"
        )
        notifier.notify(dup_notification)
        assert len(sent_telegram_messages) == initial_count, "Duplicate alert was not suppressed!"
        print("Verified duplicate Creation notification was suppressed successfully.")

        # Scenario 3: Transition from UNHEALTHY to HEALTHY (Incident Resolved)
        print("\n[Step 3] Triggering incident resolution...")
        resolved_inc = resolve_incident(
            target_name="HexaBeta Backend API",
            notifier=notifier,
            endpoint="http://localhost:8002/api/health"
        )
        
        print("\n--- Outbound Telegram Alert Resolved Message ---")
        print(sent_telegram_messages[-1])
        print("-----------------------------------------------\n")
        
        resolved_msg = sent_telegram_messages[-1]
        assert "Incident Resolved" in resolved_msg
        assert f"Incident ID: {incident.id}" in resolved_msg
        assert "Target: HexaBeta Backend API" in resolved_msg
        assert "Recovered At:" in resolved_msg
        assert "Duration:" in resolved_msg
        assert "Status: RESOLVED" in resolved_msg
        assert "Developer Guidance" in resolved_msg
        
        # Scenario 4: Deduplication Suppression after RESOLVED
        print("\n[Step 4] Attempting duplicate resolution alert dispatch...")
        initial_count = len(sent_telegram_messages)
        dup_resolved = Notification(
            notification_type=NotificationType.INCIDENT_RESOLVED,
            incident_id=incident.id,
            target_name="HexaBeta Backend API",
            status=NotificationStatus.PENDING,
            created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            message="Duplicate resolve attempt"
        )
        notifier.notify(dup_resolved)
        assert len(sent_telegram_messages) == initial_count, "Duplicate recovery alert was not suppressed!"
        print("Verified duplicate Resolution notification was suppressed successfully.")
        
        # Scenario 5: Bounded Cleanup allows subsequent incidents
        print("\n[Step 5] Triggering a new incident to verify tracking cleanups...")
        new_incident = create_incident(
            target_name="HexaBeta Backend API",
            failure_reason="Connection Timeout",
            verification_attempts=2,
            config=config,
            notifier=notifier,
            endpoint="http://localhost:8002/api/health"
        )
        # Verify we allowed a new incident ID creation alert to pass
        assert sent_telegram_messages[-1] != resolved_msg
        assert f"Incident ID: {new_incident.id}" in sent_telegram_messages[-1]
        print(f"Verified new incident creation alert dispatched: {new_incident.id}")

    # Cleanup temp incidents on disk
    for inc_id in [incident.id, new_incident.id]:
        temp_dir = os.path.join("incidents", inc_id)
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
            
    print("\n==================================================")
    print("TYPE 2 INTEGRATION VERIFIED SUCCESSFULLY")
    print("==================================================")

if __name__ == "__main__":
    if sys.stdout.encoding != 'utf-8':
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            pass
    run_type2_integration()
