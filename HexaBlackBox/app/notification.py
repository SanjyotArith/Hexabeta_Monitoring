from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict

class NotificationType(Enum):
    INCIDENT_CREATED = "INCIDENT_CREATED"
    INCIDENT_RESOLVED = "INCIDENT_RESOLVED"

class NotificationStatus(Enum):
    """
    Represents the operational status of an outgoing notification dispatch.
    
    This Enum can be extended in future releases to support more granular states
    (e.g., RETRYING, SKIPPED, PARTIALLY_SENT) without breaking external APIs.
    """
    PENDING = "PENDING"      # The alert is queued or initialized but not yet dispatched
    SENT = "SENT"            # All registered providers completed transmission successfully
    FAILED = "FAILED"        # One or more providers failed to transmit the alert

@dataclass
class Notification:
    notification_type: NotificationType
    incident_id: str
    target_name: str
    status: NotificationStatus
    created_at: str
    message: str
    metadata: Dict[str, Any] = field(default_factory=dict)
