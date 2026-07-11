import sys
from app.config import load_config
from app.monitor import start_monitoring

def main():
    try:
        # Load and validate configuration
        config = load_config("config/config.yaml")
        
        # Start the monitoring loop
        start_monitoring(config)
        
    except KeyboardInterrupt:
        print("\nHexaBlackBox monitoring stopped by user. Exiting cleanly.")
        sys.exit(0)

if __name__ == "__main__":
    main()
