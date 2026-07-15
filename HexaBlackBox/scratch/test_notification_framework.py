import sys
import os
from datetime import datetime, timezone
from abc import ABC

# Adjust search path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.notification import Notification, NotificationType, NotificationStatus
from app.notifier import NotificationProvider, NotificationManager

# Concrete provider implementation for testing
class DummyProvider(NotificationProvider):
    def __init__(self, name: str, return_value: bool = True, raise_err: Exception = None):
        self.name = name
        self.return_value = return_value
        self.raise_err = raise_err
        self.called_with = []

    def send(self, notification: Notification) -> bool:
        self.called_with.append(notification)
        if self.raise_err:
            raise self.raise_err
        return self.return_value

# Incomplete provider subclass to test ABC enforcement
class IncompleteProvider(NotificationProvider):
    pass

def test_notification_domain():
    print("Notification Domain ... ", end="", flush=True)
    
    # Enum asserts
    assert NotificationType.INCIDENT_CREATED.value == "INCIDENT_CREATED"
    assert NotificationType.INCIDENT_RESOLVED.value == "INCIDENT_RESOLVED"
    
    assert NotificationStatus.PENDING.value == "PENDING"
    assert NotificationStatus.SENT.value == "SENT"
    assert NotificationStatus.FAILED.value == "FAILED"
    
    # Dataclass creation and UTC validation
    utc_now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    n1 = Notification(
        notification_type=NotificationType.INCIDENT_CREATED,
        incident_id="INC-2026-0001",
        target_name="TestTarget",
        status=NotificationStatus.PENDING,
        created_at=utc_now,
        message="Failure detected"
    )
    
    assert n1.notification_type == NotificationType.INCIDENT_CREATED
    assert n1.incident_id == "INC-2026-0001"
    assert n1.target_name == "TestTarget"
    assert n1.status == NotificationStatus.PENDING
    assert n1.created_at == utc_now
    assert n1.message == "Failure detected"
    assert n1.metadata == {}
    
    # Metadata isolation check (independent dictionaries)
    n1.metadata["key"] = "val"
    n2 = Notification(
        notification_type=NotificationType.INCIDENT_RESOLVED,
        incident_id="INC-2026-0002",
        target_name="TestTarget2",
        status=NotificationStatus.SENT,
        created_at=utc_now,
        message="Resolved"
    )
    assert n2.metadata == {}
    
    print("PASSED")

def test_notification_provider():
    print("NotificationProvider ... ", end="", flush=True)
    
    # Verify ABC enforcement
    try:
        NotificationProvider()
        raise AssertionError("Should not be able to instantiate ABC NotificationProvider directly")
    except TypeError:
        pass
        
    try:
        IncompleteProvider()
        raise AssertionError("Should not be able to instantiate IncompleteProvider with missing send()")
    except TypeError:
        pass
        
    # Verify concrete implementation works
    dummy = DummyProvider("dummy")
    assert isinstance(dummy, NotificationProvider)
    
    n = Notification(
        notification_type=NotificationType.INCIDENT_CREATED,
        incident_id="INC-1",
        target_name="T",
        status=NotificationStatus.PENDING,
        created_at="now",
        message="msg"
    )
    assert dummy.send(n) is True
    assert len(dummy.called_with) == 1
    
    print("PASSED")

def test_notification_manager():
    print("NotificationManager ... ", end="", flush=True)
    
    n = Notification(
        notification_type=NotificationType.INCIDENT_CREATED,
        incident_id="INC-1",
        target_name="T",
        status=NotificationStatus.PENDING,
        created_at="now",
        message="msg"
    )
    
    # 1. Empty registry returns True
    manager = NotificationManager()
    assert manager.notify(n) is True
    
    # 2. Valid provider registration
    provider1 = DummyProvider("p1", return_value=True)
    manager.register_provider(provider1)
    assert len(manager._providers) == 1
    
    # 3. Invalid provider registration
    try:
        manager.register_provider("not_a_provider")
        raise AssertionError("Should raise TypeError on invalid provider registration")
    except TypeError:
        pass
        
    # 4. Duplicate registration (documented behavior: appends multiple times)
    manager.register_provider(provider1)
    assert len(manager._providers) == 2
    
    # 5. Success/Failure return values propagation
    m2 = NotificationManager()
    p_success = DummyProvider("success", return_value=True)
    p_fail = DummyProvider("fail", return_value=False)
    
    m2.register_provider(p_success)
    assert m2.notify(n) is True
    
    m2.register_provider(p_fail)
    assert m2.notify(n) is False  # one fail -> False
    
    # Providers execution in registration order check
    m3 = NotificationManager()
    order = []
    class OrderProvider(NotificationProvider):
        def __init__(self, idx):
            self.idx = idx
        def send(self, notification):
            order.append(self.idx)
            return True
            
    m3.register_provider(OrderProvider(1))
    m3.register_provider(OrderProvider(2))
    m3.register_provider(OrderProvider(3))
    
    assert m3.notify(n) is True
    assert order == [1, 2, 3]
    
    print("PASSED")

def test_exception_isolation():
    print("Exception Isolation ... ", end="", flush=True)
    
    n = Notification(
        notification_type=NotificationType.INCIDENT_CREATED,
        incident_id="INC-1",
        target_name="T",
        status=NotificationStatus.PENDING,
        created_at="now",
        message="msg"
    )
    
    manager = NotificationManager()
    p1 = DummyProvider("p1", return_value=True)
    p_crash = DummyProvider("p_crash", raise_err=RuntimeError("API is down"))
    p2 = DummyProvider("p2", return_value=True)
    
    manager.register_provider(p1)
    manager.register_provider(p_crash)
    manager.register_provider(p2)
    
    # Should run all providers, handle crash, and return False (overall fail)
    assert manager.notify(n) is False
    assert len(p1.called_with) == 1
    assert len(p_crash.called_with) == 1
    assert len(p2.called_with) == 1  # p2 executed despite p_crash raising an exception
    
    print("PASSED")

def test_regression():
    print("Regression ... ", end="", flush=True)
    
    # Check key files exist and are not missing properties
    from app.monitor import execute_check
    from app.incident import is_incident_active
    from app.collector import CollectorManager
    
    assert execute_check is not None
    assert is_incident_active is not None
    assert len(CollectorManager._registry) >= 7
    
    # Assert no production code files were modified except notifier/notification
    # (Checked by repository status checks)
    
    print("PASSED")

def test_edge_cases():
    print("Edge Cases ... ", end="", flush=True)
    
    n = Notification(
        notification_type=NotificationType.INCIDENT_CREATED,
        incident_id="INC-1",
        target_name="T",
        status=NotificationStatus.PENDING,
        created_at="now",
        message="msg",
        metadata={"val": 42}
    )
    
    manager = NotificationManager()
    p1 = DummyProvider("p1", return_value=True)
    p_generic_crash = DummyProvider("p_generic_crash", raise_err=Exception("Unknown Error"))
    
    manager.register_provider(p1)
    manager.register_provider(p_generic_crash)
    
    # Multiple consecutive notify calls
    assert manager.notify(n) is False
    assert manager.notify(n) is False
    
    # Metadata is not mutated during dispatches
    assert n.metadata == {"val": 42}
    
    print("PASSED")

def main():
    print("==================================================")
    print("Starting Type 1 Verification")
    print("==================================================")
    try:
        test_notification_domain()
        test_notification_provider()
        test_notification_manager()
        test_exception_isolation()
        test_regression()
        test_edge_cases()
        
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
