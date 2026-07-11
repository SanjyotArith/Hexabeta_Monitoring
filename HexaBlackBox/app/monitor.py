import time
from app.checks import execute_check

def format_result(result) -> str:
    """
    Formats the HealthCheckResult for console display.
    Format: [timestamp] Target: name | Status: HEALTHY/UNHEALTHY | Response Time: Xms | Reason: reason
    """
    reason_str = result.reason if result.reason is not None else "None"
    return (
        f"[{result.timestamp}] Target: {result.target_name} | "
        f"Status: {result.status} | "
        f"Response Time: {result.response_time_ms}ms | "
        f"Reason: {reason_str}"
    )

def start_monitoring(config: dict):
    """
    Continuous monitoring loop.
    Iterates sequentially through configured targets, runs checks, prints results,
    and sleeps for the target's interval.
    """
    targets = config["targets"]
    print("Starting HexaBlackBox Core Monitoring Engine...")
    print(f"Monitoring {len(targets)} target(s). Press Ctrl+C to exit.\n")
    
    while True:
        for target in targets:
            result = execute_check(target)
            print(format_result(result), flush=True)
            time.sleep(target["interval"])
