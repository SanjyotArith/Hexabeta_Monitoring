import json
import urllib.request
import urllib.error
from app.notification import Notification, NotificationType
from app.notifier import NotificationProvider

class TelegramProvider(NotificationProvider):
    """
    Alert notification delivery provider for Telegram Messenger using the Bot HTTP API.
    """
    def __init__(self, bot_token: str, chat_id: str, timeout: int = 5) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.timeout = timeout

    def send(self, notification: Notification) -> bool:
        """
        Processes and transmits the notification alert to the configured Telegram chat.
        Returns True on success, or False on failure.
        """
        try:
            message = self._build_message(notification)
            return self._send_request(message)
        except Exception:
            # Shield core framework from any unhandled formatting or connection errors
            return False

    def _build_message(self, notification: Notification) -> str:
        """
        Constructs the string payload representation of the alert message.
        """
        host = notification.metadata.get("host", "Unknown Host")
        endpoint = notification.metadata.get("endpoint", "N/A")
        inc_dir = notification.metadata.get("incident_dir", "N/A")
        inc_json = notification.metadata.get("incident_json", "N/A")
        evidence = notification.metadata.get("evidence_package", "none")
        
        # Format Developer Guidance cleanly
        guidance = (
            f"Developer Guidance\n\n"
            f"📁 Incident Folder\n"
            f"{inc_dir}/\n\n"
            f"📄 Incident Package\n"
            f"{inc_json}"
        )
        if evidence == "available":
            guidance += "\n\n📦 Evidence\nCollector diagnostics included."
        
        if notification.notification_type == NotificationType.INCIDENT_CREATED:
            raw_reason = notification.metadata.get("failure_reason", "Unknown failure")
            
            # Format failure reasons to be concise and operator-friendly
            failure_reason = raw_reason.strip()
            if "HTTP status code" in failure_reason:
                parts = failure_reason.split()
                if parts:
                    code = parts[-1]
                    status_map = {
                        "500": "Internal Server Error",
                        "502": "Bad Gateway",
                        "503": "Service Unavailable",
                        "504": "Gateway Timeout",
                        "400": "Bad Request",
                        "401": "Unauthorized",
                        "403": "Forbidden",
                        "404": "Not Found"
                    }
                    desc = status_map.get(code, "Error")
                    failure_reason = f"HTTP {code} {desc}"
            elif "connection failed" in failure_reason.lower():
                failure_reason = "Connection Failed"
            elif "connection refused" in failure_reason.lower():
                failure_reason = "Connection Refused"
            elif "timeout" in failure_reason.lower():
                failure_reason = "Timeout"
            elif "dns resolution" in failure_reason.lower():
                failure_reason = "DNS Resolution Failed"
            elif "ssl" in failure_reason.lower():
                failure_reason = "SSL Failure"
            elif "validation" in failure_reason.lower():
                failure_reason = "Validation Failure"

            return (
                f"HexaBlackBox\n\n"
                f"Incident Created\n\n"
                f"Incident ID: {notification.incident_id}\n"
                f"Target: {notification.target_name}\n"
                f"Host: {host}\n"
                f"Endpoint: {endpoint}\n"
                f"Started At: {notification.created_at}\n"
                f"Status: ACTIVE\n"
                f"Failure: {failure_reason}\n\n"
                f"{guidance}"
            )
        elif notification.notification_type == NotificationType.INCIDENT_RESOLVED:
            resolved_at = notification.metadata.get("resolved_at", notification.created_at)
            duration_sec = notification.metadata.get("duration_seconds", 0)
            return (
                f"HexaBlackBox\n\n"
                f"Incident Resolved\n\n"
                f"Incident ID: {notification.incident_id}\n"
                f"Target: {notification.target_name}\n"
                f"Host: {host}\n"
                f"Recovered At: {resolved_at}\n"
                f"Duration: {duration_sec} seconds\n"
                f"Status: RESOLVED\n\n"
                f"{guidance}"
            )
        else:
            return f"HexaBlackBox\n\nTarget: {notification.target_name}\nMessage: {notification.message}"

    def _send_request(self, message: str) -> bool:
        """
        Dispatches the HTTP POST request to Telegram API endpoints.
        """
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message
        }
        
        headers = {
            "Content-Type": "application/json"
        }
        
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                if response.status != 200:
                    return False
                
                resp_data = json.loads(response.read().decode("utf-8"))
                return resp_data.get("ok") is True
                
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            return False
        except Exception:
            return False
