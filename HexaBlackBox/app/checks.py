import time
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, Any, Callable
import requests

@dataclass
class HealthCheckResult:
    timestamp: str
    target_name: str
    status: str            # "HEALTHY" or "UNHEALTHY"
    http_status: Optional[int]
    response_time_ms: float
    reason: Optional[str]

# Define individual validator functions that are easily extensible
def validate_status_code(response: requests.Response, expected: Any) -> tuple[bool, Optional[str]]:
    try:
        expected_status = int(expected)
        if response.status_code == expected_status:
            return True, None
        return False, f"Expected status code {expected_status}, got {response.status_code}"
    except (ValueError, TypeError):
        return False, f"Invalid expected status code rule: {expected}"

def validate_body_contains(response: requests.Response, expected: Any) -> tuple[bool, Optional[str]]:
    expected_str = str(expected)
    if expected_str in response.text:
        return True, None
    return False, f"Response body did not contain substring '{expected_str}'"

# Registry mapping validation keys to validation functions
VALIDATORS: dict[str, Callable[[requests.Response, Any], tuple[bool, Optional[str]]]] = {
    "status_code": validate_status_code,
    "body_contains": validate_body_contains,
}

def run_validation(response: requests.Response, rules: dict) -> tuple[bool, Optional[str]]:
    """
    Validates a response based on the configuration-driven rules.
    Returns (is_valid, failure_reason).
    """
    # If no status_code validation is specified, default to status_code: 200
    if "status_code" not in rules:
        valid, reason = validate_status_code(response, 200)
        if not valid:
            return False, reason

    for rule_name, rule_value in rules.items():
        validator = VALIDATORS.get(rule_name)
        if not validator:
            return False, f"Unknown validation rule: '{rule_name}'"
        
        valid, reason = validator(response, rule_value)
        if not valid:
            return False, reason
            
    return True, None

def execute_check(target: dict) -> HealthCheckResult:
    """
    Executes a health check for a given target and returns a HealthCheckResult.
    """
    name = target["name"]
    endpoint = target["endpoint"]
    method = target.get("method", "GET")
    timeout = target.get("timeout", 5)
    validation_rules = target.get("validation", {})
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    start_time = time.perf_counter()
    try:
        response = requests.request(
            method=method,
            url=endpoint,
            timeout=timeout
        )
        response_time_ms = (time.perf_counter() - start_time) * 1000.0
        
        # Run validation
        is_healthy, reason = run_validation(response, validation_rules)
        status = "HEALTHY" if is_healthy else "UNHEALTHY"
        
        return HealthCheckResult(
            timestamp=timestamp,
            target_name=name,
            status=status,
            http_status=response.status_code,
            response_time_ms=round(response_time_ms, 2),
            reason=reason
        )
        
    except requests.exceptions.Timeout:
        response_time_ms = (time.perf_counter() - start_time) * 1000.0
        return HealthCheckResult(
            timestamp=timestamp,
            target_name=name,
            status="UNHEALTHY",
            http_status=None,
            response_time_ms=round(response_time_ms, 2),
            reason=f"Request timeout after {timeout}s"
        )
    except requests.exceptions.ConnectionError:
        response_time_ms = (time.perf_counter() - start_time) * 1000.0
        return HealthCheckResult(
            timestamp=timestamp,
            target_name=name,
            status="UNHEALTHY",
            http_status=None,
            response_time_ms=round(response_time_ms, 2),
            reason="Connection failed"
        )
    except Exception as e:
        response_time_ms = (time.perf_counter() - start_time) * 1000.0
        return HealthCheckResult(
            timestamp=timestamp,
            target_name=name,
            status="UNHEALTHY",
            http_status=None,
            response_time_ms=round(response_time_ms, 2),
            reason=f"Request failed: {str(e)}"
        )
