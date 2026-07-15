from abc import ABC, abstractmethod
from typing import List, Set
from app.notification import Notification, NotificationType

class NotificationProvider(ABC):
    """
    Abstract Base Class for all alert notification providers.
    All notification drivers must subclass this and implement send().
    """
    @abstractmethod
    def send(self, notification: Notification) -> bool:
        """
        Sends the notification alert using the provider's communication channel.
        Returns True on success, or False on failure.
        """
        pass

class NotificationManager:
    """
    Coordinates and broadcasts notifications to registered provider plugins.
    Ensures provider execution isolation so failure of one does not affect others.
    """
    def __init__(self, suppression_enabled: bool = True) -> None:
        self._providers: List[NotificationProvider] = []
        self.suppression_enabled = suppression_enabled
        self._dispatched_alerts: Set[str] = set()
        self._recent_resolved_ids: List[str] = []  # Bounded history queue of resolved incident IDs

    def register_provider(self, provider: NotificationProvider) -> None:
        """
        Registers a notification provider instance with the coordinator.
        """
        if not isinstance(provider, NotificationProvider):
            raise TypeError("Provider must subclass NotificationProvider")
        self._providers.append(provider)

    def notify(self, notification: Notification) -> bool:
        """
        Broadcasts the notification to all registered providers.
        Captures isolated successes/failures without leaking exceptions.
        Returns True if all registered providers successfully delivered the alert.

        Note on empty registry behaviour:
        If no providers are registered, notify() returns True. This is considered
        a successful no-op because nothing was requested to be sent. Returning
        True prevents configuration-less or testing environments from raising false
        alarms or failing core target check executions when alerts are intentionally
        not configured.
        """
        # Bounded duplication suppression check
        if self.suppression_enabled:
            dup_key = f"{notification.incident_id}:{notification.notification_type.value}"
            if dup_key in self._dispatched_alerts:
                # Duplicate alert: skip dispatch and return True as a successful no-op
                return True
            self._dispatched_alerts.add(dup_key)

        if not self._providers:
            return True

        overall_success = True
        
        for provider in self._providers:
            try:
                # Dispatch alert in isolation
                success = provider.send(notification)
                if not success:
                    overall_success = False
            except Exception:
                # Capture exceptions to prevent interrupting the core check loops
                # Failure is isolated, no logs or prints are written from this class
                overall_success = False

        # Bounded Memory Cleanup Strategy:
        # Upon resolving an incident, we keep the tracking keys active in the registry 
        # to suppress any duplicate resolution attempts. To prevent unbounded memory growth,
        # we maintain a sliding window of the 100 most recent resolved incident IDs. 
        # When this size is exceeded, the oldest incident's tracking keys are discarded.
        if self.suppression_enabled and notification.notification_type == NotificationType.INCIDENT_RESOLVED:
            if notification.incident_id not in self._recent_resolved_ids:
                self._recent_resolved_ids.append(notification.incident_id)
                if len(self._recent_resolved_ids) > 100:
                    oldest_id = self._recent_resolved_ids.pop(0)
                    self._dispatched_alerts.discard(f"{oldest_id}:{NotificationType.INCIDENT_CREATED.value}")
                    self._dispatched_alerts.discard(f"{oldest_id}:{NotificationType.INCIDENT_RESOLVED.value}")
                
        return overall_success
