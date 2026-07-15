from abc import ABC, abstractmethod
from typing import List
from app.notification import Notification

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
    def __init__(self) -> None:
        self._providers: List[NotificationProvider] = []

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
                
        return overall_success
