import sys
from app.config import load_config
from app.monitor import start_monitoring
from app.notifier import NotificationManager

def main():
    try:
        # Load and validate configuration
        config = load_config("config/config.yaml")
        
        # Extract notifier configuration
        notifier_config = config.get("notifier", {})
        suppression_enabled = notifier_config.get("suppression_enabled", True)
        
        # Instantiate NotificationManager explicitly
        notifier = NotificationManager(suppression_enabled=suppression_enabled)
        
        # Register enabled providers based on configuration
        telegram_config = notifier_config.get("telegram", {})
        telegram_config = notifier_config.get("telegram", {})
        if telegram_config.get("enabled", False):
            from app.notifier.telegram import TelegramProvider
            telegram_provider = TelegramProvider(
                bot_token=telegram_config["bot_token"],
                chat_id=telegram_config["chat_id"],
                timeout=telegram_config.get("timeout", 5)
            )
            notifier.register_provider(telegram_provider)
            
        # Instantiate RuntimeHealthManager and register core monitoring component
        from app.health import RuntimeHealthManager
        health_manager = RuntimeHealthManager()
        health_manager.register_component("monitoring_loop")
        
        # Register Snapshot Providers
        from app.snapshot.engine import SnapshotEngine
        from app.snapshot.providers import get_backend_provider
        SnapshotEngine.register_provider(get_backend_provider())
            
        # Start the monitoring loop with injected notifier and health manager
        start_monitoring(config, notifier=notifier, health_manager=health_manager)
        
    except KeyboardInterrupt:
        print("\nHexaBlackBox monitoring stopped by user. Exiting cleanly.")
        sys.exit(0)

if __name__ == "__main__":
    main()
