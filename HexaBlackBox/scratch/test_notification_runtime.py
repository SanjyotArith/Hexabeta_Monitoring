import sys
import os
from datetime import datetime, timezone
from typing import List

# Adjust search path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.notification import Notification, NotificationType, NotificationStatus
from app.notifier import NotificationProvider, NotificationManager

# Temporary Mock Providers for runtime verification
class RuntimeMockProvider(NotificationProvider):
    def __init__(self, name: str, return_value: bool = True, raise_err: Exception = None):
        self.name = name
        self.return_value = return_value
        self.raise_err = raise_err
        self.delivered_notifications: List[Notification] = []

    def send(self, notification: Notification) -> bool:
        self.delivered_notifications.append(notification)
        if self.raise_err:
            raise self.raise_err
        return self.return_value

class ExecutionOrderTracker:
    def __init__(self):
        self.order: List[str] = []

class OrderedMockProvider(NotificationProvider):
    def __init__(self, name: str, tracker: ExecutionOrderTracker):
        self.name = name
        self.tracker = tracker

    def send(self, notification: Notification) -> bool:
        self.tracker.order.append(self.name)
        return True

def run_type2_verification():
    print("==================================================")
    print("Starting Type 2 Verification")
    print("==================================================")
    
    results = {
        "Single Provider": False,
        "Multiple Providers": False,
        "Provider Failure": False,
        "Provider Exception": False,
        "Multiple Notifications": False,
        "Empty Registry": False,
        "Notification Integrity": False,
        "Regression": False
    }

    # 1. Single Provider
    try:
        manager = NotificationManager()
        p1 = RuntimeMockProvider("P1", return_value=True)
        manager.register_provider(p1)
        
        n = Notification(
            notification_type=NotificationType.INCIDENT_CREATED,
            incident_id="INC-T2-0001",
            target_name="SingleTarget",
            status=NotificationStatus.PENDING,
            created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            message="Single Provider test alert"
        )
        
        ret = manager.notify(n)
        assert ret is True
        assert len(p1.delivered_notifications) == 1
        assert p1.delivered_notifications[0] == n
        results["Single Provider"] = True
    except Exception as e:
        print(f"Single Provider failed: {e}")

    # 2. Multiple Providers (Order Validation)
    try:
        tracker = ExecutionOrderTracker()
        manager = NotificationManager()
        
        p1 = OrderedMockProvider("First", tracker)
        p2 = OrderedMockProvider("Second", tracker)
        p3 = OrderedMockProvider("Third", tracker)
        
        manager.register_provider(p1)
        manager.register_provider(p2)
        manager.register_provider(p3)
        
        n = Notification(
            notification_type=NotificationType.INCIDENT_CREATED,
            incident_id="INC-T2-0002",
            target_name="MultiTarget",
            status=NotificationStatus.PENDING,
            created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            message="Multiple Providers test alert"
        )
        
        ret = manager.notify(n)
        assert ret is True
        assert tracker.order == ["First", "Second", "Third"]
        results["Multiple Providers"] = True
    except Exception as e:
        print(f"Multiple Providers failed: {e}")

    # 3. Provider Failure
    try:
        manager = NotificationManager()
        pa = RuntimeMockProvider("A", return_value=True)
        pb = RuntimeMockProvider("B", return_value=False)
        pc = RuntimeMockProvider("C", return_value=True)
        
        manager.register_provider(pa)
        manager.register_provider(pb)
        manager.register_provider(pc)
        
        n = Notification(
            notification_type=NotificationType.INCIDENT_CREATED,
            incident_id="INC-T2-0003",
            target_name="FailTarget",
            status=NotificationStatus.PENDING,
            created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            message="Provider Failure test alert"
        )
        
        ret = manager.notify(n)
        assert ret is False
        assert len(pa.delivered_notifications) == 1
        assert len(pb.delivered_notifications) == 1
        assert len(pc.delivered_notifications) == 1  # C still executed
        results["Provider Failure"] = True
    except Exception as e:
        print(f"Provider Failure failed: {e}")

    # 4. Provider Exception Isolation
    try:
        manager = NotificationManager()
        pa = RuntimeMockProvider("A", return_value=True)
        pb = RuntimeMockProvider("B", raise_err=RuntimeError("Connection refused"))
        pc = RuntimeMockProvider("C", return_value=True)
        
        manager.register_provider(pa)
        manager.register_provider(pb)
        manager.register_provider(pc)
        
        n = Notification(
            notification_type=NotificationType.INCIDENT_CREATED,
            incident_id="INC-T2-0004",
            target_name="ExceptionTarget",
            status=NotificationStatus.PENDING,
            created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            message="Provider Exception test alert"
        )
        
        # Exception should not propagate outside notify()
        ret = manager.notify(n)
        assert ret is False
        assert len(pa.delivered_notifications) == 1
        assert len(pb.delivered_notifications) == 1
        assert len(pc.delivered_notifications) == 1  # C still executed
        results["Provider Exception"] = True
    except Exception as e:
        print(f"Provider Exception failed: {e}")

    # 5. Multiple Notifications
    try:
        manager = NotificationManager()
        p1 = RuntimeMockProvider("P1", return_value=True)
        manager.register_provider(p1)
        
        n1 = Notification(
            notification_type=NotificationType.INCIDENT_CREATED,
            incident_id="INC-T2-0005A",
            target_name="TargetA",
            status=NotificationStatus.PENDING,
            created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            message="Alert A"
        )
        n2 = Notification(
            notification_type=NotificationType.INCIDENT_RESOLVED,
            incident_id="INC-T2-0005B",
            target_name="TargetB",
            status=NotificationStatus.SENT,
            created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            message="Alert B"
        )
        
        ret1 = manager.notify(n1)
        ret2 = manager.notify(n2)
        
        assert ret1 is True
        assert ret2 is True
        assert len(p1.delivered_notifications) == 2
        assert p1.delivered_notifications[0] == n1
        assert p1.delivered_notifications[1] == n2
        results["Multiple Notifications"] = True
    except Exception as e:
        print(f"Multiple Notifications failed: {e}")

    # 6. Empty Registry
    try:
        manager = NotificationManager()
        n = Notification(
            notification_type=NotificationType.INCIDENT_CREATED,
            incident_id="INC-T2-0006",
            target_name="EmptyTarget",
            status=NotificationStatus.PENDING,
            created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            message="Empty Registry test alert"
        )
        ret = manager.notify(n)
        assert ret is True
        results["Empty Registry"] = True
    except Exception as e:
        print(f"Empty Registry failed: {e}")

    # 7. Notification Integrity
    try:
        manager = NotificationManager()
        p1 = RuntimeMockProvider("P1", return_value=True)
        manager.register_provider(p1)
        
        created_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        n = Notification(
            notification_type=NotificationType.INCIDENT_CREATED,
            incident_id="INC-T2-0007",
            target_name="IntegrityTarget",
            status=NotificationStatus.PENDING,
            created_at=created_time,
            message="Integrity check alert",
            metadata={"source": "test"}
        )
        
        # Verify state before dispatch
        assert n.notification_type == NotificationType.INCIDENT_CREATED
        assert n.incident_id == "INC-T2-0007"
        assert n.target_name == "IntegrityTarget"
        assert n.status == NotificationStatus.PENDING
        assert n.created_at == created_time
        assert n.message == "Integrity check alert"
        assert n.metadata == {"source": "test"}
        
        manager.notify(n)
        
        # Verify state after dispatch
        assert n.notification_type == NotificationType.INCIDENT_CREATED
        assert n.incident_id == "INC-T2-0007"
        assert n.target_name == "IntegrityTarget"
        assert n.status == NotificationStatus.PENDING
        assert n.created_at == created_time
        assert n.message == "Integrity check alert"
        assert n.metadata == {"source": "test"}
        results["Notification Integrity"] = True
    except Exception as e:
        print(f"Notification Integrity failed: {e}")

    # 8. Regression
    try:
        # Check that existing collectors remain unchanged and importable
        from app.collector import CollectorManager
        from app.storage import INCIDENTS_DIR
        assert len(CollectorManager._registry) >= 7
        assert isinstance(INCIDENTS_DIR, str)
        results["Regression"] = True
    except Exception as e:
        print(f"Regression failed: {e}")

    # Print results
    print("\n--------------------------------------------------")
    for test_name, passed in results.items():
        dots = "." * (29 - len(test_name))
        status = "PASSED" if passed else "FAILED"
        print(f"{test_name} {dots} {status}")
    print("--------------------------------------------------")
    
    all_passed = all(results.values())
    if all_passed:
        print("\n==================================================")
        print("ALL TESTS PASSED")
        print("TYPE 2 VERIFIED")
        print("==================================================")
    else:
        print("\n==================================================")
        print("SOME TESTS FAILED")
        print("==================================================")

if __name__ == "__main__":
    run_type2_verification()
