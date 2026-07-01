from datetime import datetime
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.telemetry import Settings

async def send_slack_notification(db: AsyncSession, message: str, severity: str = "warning"):
    """
    Sends a structured Slack notification.
    Webhooks are dynamically retrieved from the settings table.
    """
    result = await db.execute(select(Settings).where(Settings.key == "slack_webhook_url"))
    setting = result.scalars().first()
    
    if not setting or not setting.value:
        # Fallback to console print if webhook is not configured yet
        print(f"[Slack Notifier - Muted (No Webhook)]: {message}")
        return
        
    webhook_url = setting.value
    
    # Map colors and icons based on alert severity
    color = "#10b981"  # Default Emerald Green (Uptime/Resolved)
    emoji = "✅"
    
    if severity == "critical":
        color = "#ef4444"  # Red
        emoji = "🚨"
    elif severity == "warning":
        color = "#f59e0b"  # Orange/Amber
        emoji = "⚠️"
    elif severity == "info":
        color = "#3b82f6"  # Blue
        emoji = "ℹ️"
        
    payload = {
        "attachments": [
            {
                "fallback": message,
                "color": color,
                "pretext": f"{emoji} *HexaMonitor Infrastructure Update*",
                "fields": [
                    {
                        "title": "Alert message",
                        "value": message,
                        "short": False
                    }
                ],
                "footer": "HexaMonitor Engine",
                "ts": int(datetime.utcnow().timestamp())
            }
        ]
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(webhook_url, json=payload, timeout=5)
            if response.status_code not in (200, 201):
                print(f"Error sending Slack notification: HTTP {response.status_code} - {response.text}")
    except Exception as e:
        print(f"Exception raised while connecting to Slack webhook: {e}")
