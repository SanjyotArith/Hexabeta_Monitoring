import time
from datetime import datetime
from app.checks import execute_check
from app.incident import is_incident_active, get_incident
from app.snapshot.workflow import IncidentWorkflow

def format_result(result) -> str:
    """
    Formats the HealthCheckResult for console display.
    """
    reason_str = result.reason if result.reason is not None else "None"
    
    # Check if an incident is active for this target to append the info
    active_inc = get_incident(result.target_name)
    if active_inc:
        suffix = f" (Incident Active: {active_inc.id})"
    else:
        suffix = ""

    return (
        f"[{result.timestamp}] Target: {result.target_name} | "
        f"Status: {result.status} | "
        f"Response Time: {result.response_time_ms}ms | "
        f"Reason: {reason_str}{suffix}"
    )

def start_monitoring(config: dict, notifier=None, health_manager=None):
    """
    Continuous monitoring loop.
    Iterates sequentially through configured targets, runs checks, prints results,
    manages verification states and incident creation, and sleeps.
    """
    targets = config["targets"]
    incident_conf = config["incident"]
    attempts = incident_conf["verification_attempts"]
    delay = incident_conf["verification_delay"]
    
    print("Starting HexaBlackBox Core Monitoring Engine (Milestone 3)...")
    print(f"Monitoring {len(targets)} target(s). Press Ctrl+C to exit.\n")
    
    while True:
        try:
            for target in targets:
                name = target["name"]
                
                # Check if there is an active incident for this target
                if is_incident_active(name):
                    # If active, skip verification logic, run check, and print status with incident active suffix
                    result = execute_check(target)
                    print(format_result(result), flush=True)
                    
                    if result.status == "HEALTHY":
                        from app.incident import resolve_incident
                        resolved_inc = resolve_incident(name, notifier=notifier, endpoint=target.get("endpoint"))
                        if resolved_inc:
                            print(
                                f"\n--------------------------------------------------\n"
                                f"Target Recovered\n\n"
                                f"Incident ID : {resolved_inc.id}\n\n"
                                f"Target      : {resolved_inc.target_name}\n\n"
                                f"Recovered At: {resolved_inc.resolved_at}\n\n"
                                f"Duration    : {resolved_inc.duration_seconds} seconds\n\n"
                                f"Status      : {resolved_inc.status}\n"
                                f"--------------------------------------------------\n",
                                flush=True
                            )
                    time.sleep(target["interval"])
                    continue
                    
                # If not active, run regular check
                result = execute_check(target)
                
                if result.status == "HEALTHY":
                    print(format_result(result), flush=True)
                else:
                    # Target is UNHEALTHY and no active incident exists -> Enter Verification State
                    print(format_result(result), flush=True)
                    
                    transition_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    print(f"[{transition_time}] Target: {name} | Entering Verification State | Reason: {result.reason}", flush=True)
                    
                    verification_successful = False
                    last_reason = result.reason
                    
                    for attempt in range(1, attempts + 1):
                        time.sleep(delay)
                        v_result = execute_check(target)
                        last_reason = v_result.reason
                        
                        print(
                            f"[{v_result.timestamp}] Target: {name} | "
                            f"Verification Attempt {attempt}/{attempts} | "
                            f"Status: {v_result.status} | "
                            f"Reason: {v_result.reason if v_result.reason is not None else 'None'}",
                            flush=True
                        )
                        
                        if v_result.status == "HEALTHY":
                            verification_successful = True
                            success_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            print(f"[{success_time}] Target: {name} | Verification Succeeded | Status: HEALTHY (False Alarm)", flush=True)
                            break
                            
                    if not verification_successful:
                        # Create active incident
                        incident = IncidentWorkflow.trigger_created(name, last_reason or "Unknown failure", attempts, config, notifier=notifier, endpoint=target.get("endpoint"))
                        fail_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        print(f"[{fail_time}] Target: {name} | Verification Failed | Creating Incident...", flush=True)
                        print(f"[{fail_time}] Target: {name} | Incident Created | Status: ACTIVE | Incident ID: {incident.id}", flush=True)
                
                time.sleep(target["interval"])
                
            # Cycle finished successfully
            if health_manager:
                health_manager.heartbeat("monitoring_loop")
                health_manager.mark_success("monitoring_loop")
                
        except Exception as e:
            if health_manager:
                health_manager.heartbeat("monitoring_loop")
                health_manager.mark_failure("monitoring_loop", str(e))
            raise e
