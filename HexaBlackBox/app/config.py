import os
import sys
import yaml

def load_config(config_path: str = "config/config.yaml") -> dict:
    """
    Loads and validates the configuration from the given YAML file.
    Exits immediately with a status code of 1 if loading or validation fails.
    """
    if not os.path.exists(config_path):
        print(f"Error: Configuration file not found at '{config_path}'", file=sys.stderr)
        sys.exit(1)
        
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        print(f"Error: Failed to parse YAML configuration: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: Failed to read configuration file: {e}", file=sys.stderr)
        sys.exit(1)

    if not config or not isinstance(config, dict):
        print("Error: Configuration must be a valid YAML dictionary", file=sys.stderr)
        sys.exit(1)

    targets = config.get("targets")
    if not targets:
        print("Error: Configuration must define at least one target under 'targets'", file=sys.stderr)
        sys.exit(1)
        
    if not isinstance(targets, list):
        print("Error: 'targets' must be a list", file=sys.stderr)
        sys.exit(1)

    validated_targets = []
    for idx, target in enumerate(targets):
        if not isinstance(target, dict):
            print(f"Error: Target at index {idx} is not a valid dictionary", file=sys.stderr)
            sys.exit(1)

        name = target.get("name")
        if not name or not isinstance(name, str):
            print(f"Error: Target at index {idx} must have a non-empty string 'name'", file=sys.stderr)
            sys.exit(1)

        endpoint = target.get("endpoint")
        if not endpoint or not isinstance(endpoint, str):
            print(f"Error: Target '{name}' must have a non-empty string 'endpoint'", file=sys.stderr)
            sys.exit(1)

        if not (endpoint.startswith("http://") or endpoint.startswith("https://")):
            print(f"Error: Target '{name}' has invalid endpoint '{endpoint}'. Must start with http:// or https://", file=sys.stderr)
            sys.exit(1)

        method = target.get("method", "GET")
        if not isinstance(method, str) or method.upper() not in ["GET", "POST", "PUT", "DELETE", "HEAD", "PATCH", "OPTIONS"]:
            print(f"Error: Target '{name}' has invalid HTTP method '{method}'", file=sys.stderr)
            sys.exit(1)

        interval = target.get("interval", 10)
        try:
            interval = int(interval)
            if interval < 1:
                raise ValueError
        except (ValueError, TypeError):
            print(f"Error: Target '{name}' has invalid interval '{interval}'. Must be an integer >= 1", file=sys.stderr)
            sys.exit(1)

        timeout = target.get("timeout", 5)
        try:
            timeout = int(timeout)
            if timeout < 1:
                raise ValueError
        except (ValueError, TypeError):
            print(f"Error: Target '{name}' has invalid timeout '{timeout}'. Must be an integer >= 1", file=sys.stderr)
            sys.exit(1)

        validation = target.get("validation", {"status_code": 200})
        if not isinstance(validation, dict):
            print(f"Error: Target '{name}' validation must be a dictionary", file=sys.stderr)
            sys.exit(1)

        validated_targets.append({
            "name": name,
            "endpoint": endpoint,
            "method": method.upper(),
            "interval": interval,
            "timeout": timeout,
            "validation": validation
        })

    # Validate incident parameters
    incident_conf = config.get("incident", {})
    if not isinstance(incident_conf, dict):
        print("Error: 'incident' configuration must be a dictionary", file=sys.stderr)
        sys.exit(1)

    verification_attempts = incident_conf.get("verification_attempts", 2)
    try:
        verification_attempts = int(verification_attempts)
        if verification_attempts < 1:
            raise ValueError
    except (ValueError, TypeError):
        print(f"Error: 'verification_attempts' must be an integer >= 1. Got '{verification_attempts}'", file=sys.stderr)
        sys.exit(1)

    verification_delay = incident_conf.get("verification_delay", 2)
    try:
        verification_delay = int(verification_delay)
        if verification_delay < 1:
            raise ValueError
    except (ValueError, TypeError):
        print(f"Error: 'verification_delay' must be an integer >= 1. Got '{verification_delay}'", file=sys.stderr)
        sys.exit(1)

    return {
        "targets": validated_targets,
        "incident": {
            "verification_attempts": verification_attempts,
            "verification_delay": verification_delay
        }
    }
