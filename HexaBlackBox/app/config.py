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

    # Load and merge local override config if present
    config_dir = os.path.dirname(config_path)
    config_local_path = os.path.join(config_dir, "config.local.yaml")
    if os.path.exists(config_local_path):
        try:
            with open(config_local_path, "r", encoding="utf-8") as lf:
                local_config = yaml.safe_load(lf)
            if local_config and isinstance(local_config, dict):
                def merge(d1, d2):
                    for k, v in d2.items():
                        if k in d1 and isinstance(d1[k], dict) and isinstance(v, dict):
                            merge(d1[k], v)
                        else:
                            d1[k] = v
                    return d1
                config = merge(config, local_config)
        except yaml.YAMLError as e:
            print(f"Error: Failed to parse local YAML configuration: {e}", file=sys.stderr)
            sys.exit(1)
            return
        except Exception as e:
            print(f"Error: Failed to read local configuration file: {e}", file=sys.stderr)
            sys.exit(1)
            return

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

    # Validate collectors parameters
    collectors_conf = config.get("collectors", {})
    if not isinstance(collectors_conf, dict):
        print("Error: 'collectors' configuration must be a dictionary", file=sys.stderr)
        sys.exit(1)

    validated_collectors = {}
    for coll_name, coll_val in collectors_conf.items():
        if not isinstance(coll_val, dict):
            print(f"Error: Collector '{coll_name}' configuration must be a dictionary", file=sys.stderr)
            sys.exit(1)
        enabled = coll_val.get("enabled", False)
        if not isinstance(enabled, bool):
            print(f"Error: Collector '{coll_name}' enabled flag must be a boolean", file=sys.stderr)
            sys.exit(1)
            
        validated_config = {"enabled": enabled}
        
        if enabled:
            if coll_name == "nginx":
                binary_path = coll_val.get("binary_path")
                config_path = coll_val.get("config_path")
                error_log_path = coll_val.get("error_log_path")
                access_log_path = coll_val.get("access_log_path")
                log_lines = coll_val.get("log_lines", 50)
                
                if not isinstance(binary_path, str) or not binary_path:
                    print("Error: nginx 'binary_path' must be a non-empty string", file=sys.stderr)
                    sys.exit(1)
                if not isinstance(config_path, str) or not config_path:
                    print("Error: nginx 'config_path' must be a non-empty string", file=sys.stderr)
                    sys.exit(1)
                if not isinstance(error_log_path, str) or not error_log_path:
                    print("Error: nginx 'error_log_path' must be a non-empty string", file=sys.stderr)
                    sys.exit(1)
                if not isinstance(access_log_path, str) or not access_log_path:
                    print("Error: nginx 'access_log_path' must be a non-empty string", file=sys.stderr)
                    sys.exit(1)
                try:
                    log_lines = int(log_lines)
                    if log_lines < 1:
                        raise ValueError
                except (ValueError, TypeError):
                    print("Error: nginx 'log_lines' must be an integer >= 1", file=sys.stderr)
                    sys.exit(1)
                    
                validated_config.update({
                    "binary_path": binary_path,
                    "config_path": config_path,
                    "error_log_path": error_log_path,
                    "access_log_path": access_log_path,
                    "log_lines": log_lines
                })
                
            elif coll_name == "cloudflared":
                tunnel_name = coll_val.get("tunnel_name")
                config_path = coll_val.get("config_path")
                log_path = coll_val.get("log_path")
                log_lines = coll_val.get("log_lines", 50)
                
                if not isinstance(tunnel_name, str) or not tunnel_name:
                    print("Error: cloudflared 'tunnel_name' must be a non-empty string", file=sys.stderr)
                    sys.exit(1)
                if not isinstance(config_path, str) or not config_path:
                    print("Error: cloudflared 'config_path' must be a non-empty string", file=sys.stderr)
                    sys.exit(1)
                if not isinstance(log_path, str) or not log_path:
                    print("Error: cloudflared 'log_path' must be a non-empty string", file=sys.stderr)
                    sys.exit(1)
                try:
                    log_lines = int(log_lines)
                    if log_lines < 1:
                        raise ValueError
                except (ValueError, TypeError):
                    print("Error: cloudflared 'log_lines' must be an integer >= 1", file=sys.stderr)
                    sys.exit(1)
                    
                validated_config.update({
                    "tunnel_name": tunnel_name,
                    "config_path": config_path,
                    "log_path": log_path,
                    "log_lines": log_lines
                })
                
            elif coll_name == "uvicorn":
                service_label = coll_val.get("service_label")
                port = coll_val.get("port")
                expected_workers = coll_val.get("expected_workers")
                
                if not isinstance(service_label, str) or not service_label:
                    print("Error: uvicorn 'service_label' must be a non-empty string", file=sys.stderr)
                    sys.exit(1)
                try:
                    port = int(port)
                    if port < 1:
                        raise ValueError
                except (ValueError, TypeError):
                    print("Error: uvicorn 'port' must be an integer >= 1", file=sys.stderr)
                    sys.exit(1)
                try:
                    expected_workers = int(expected_workers)
                    if expected_workers < 1:
                        raise ValueError
                except (ValueError, TypeError):
                    print("Error: uvicorn 'expected_workers' must be an integer >= 1", file=sys.stderr)
                    sys.exit(1)
                    
                validated_config.update({
                    "service_label": service_label,
                    "port": port,
                    "expected_workers": expected_workers
                })

            elif coll_name == "postgres":
                timeout = coll_val.get("timeout", 5)
                try:
                    timeout = int(timeout)
                    if timeout < 1:
                        raise ValueError
                except (ValueError, TypeError):
                    print("Error: postgres 'timeout' must be an integer >= 1", file=sys.stderr)
                    sys.exit(1)
                binary_path = coll_val.get("binary_path")
                host = coll_val.get("host")
                port = coll_val.get("port")
                databases = coll_val.get("databases")
                log_path = coll_val.get("log_path")
                log_lines = coll_val.get("log_lines", 50)
                
                if not isinstance(binary_path, str) or not binary_path:
                    print("Error: postgres 'binary_path' must be a non-empty string", file=sys.stderr)
                    sys.exit(1)
                if not isinstance(host, str) or not host:
                    print("Error: postgres 'host' must be a non-empty string", file=sys.stderr)
                    sys.exit(1)
                try:
                    port = int(port)
                    if port < 1:
                        raise ValueError
                except (ValueError, TypeError):
                    print("Error: postgres 'port' must be an integer >= 1", file=sys.stderr)
                    sys.exit(1)
                if not isinstance(log_path, str) or not log_path:
                    print("Error: postgres 'log_path' must be a non-empty string", file=sys.stderr)
                    sys.exit(1)
                try:
                    log_lines = int(log_lines)
                    if log_lines < 1:
                        raise ValueError
                except (ValueError, TypeError):
                    print("Error: postgres 'log_lines' must be an integer >= 1", file=sys.stderr)
                    sys.exit(1)
                    
                # Validate databases key exists and is non-empty list
                if databases is None:
                    print("Error: postgres 'databases' key must exist", file=sys.stderr)
                    sys.exit(1)
                    return
                if not isinstance(databases, list) or len(databases) == 0:
                    print("Error: postgres 'databases' must be a non-empty list", file=sys.stderr)
                    sys.exit(1)
                    return
                    
                db_names = set()
                validated_databases = []
                for idx, db_entry in enumerate(databases):
                    if not isinstance(db_entry, dict):
                        print(f"Error: postgres database entry at index {idx} must be a dictionary", file=sys.stderr)
                        sys.exit(1)
                        return
                    
                    db_name = db_entry.get("name")
                    db_user = db_entry.get("username")
                    db_pass = db_entry.get("password")
                    
                    if db_name is None or not isinstance(db_name, str) or not db_name.strip():
                        print(f"Error: postgres database entry at index {idx} must have a non-empty string 'name'", file=sys.stderr)
                        sys.exit(1)
                        return
                    if db_user is None or not isinstance(db_user, str):
                        print(f"Error: postgres database entry at index {idx} must have a string 'username'", file=sys.stderr)
                        sys.exit(1)
                        return
                    if db_pass is None or not isinstance(db_pass, str):
                        print(f"Error: postgres database entry at index {idx} must have a string 'password'", file=sys.stderr)
                        sys.exit(1)
                        return
                        
                    if db_name in db_names:
                        print(f"Error: postgres database entry at index {idx} has duplicate 'name' '{db_name}'", file=sys.stderr)
                        sys.exit(1)
                        return
                    db_names.add(db_name)
                    
                    validated_databases.append({
                        "name": db_name,
                        "username": db_user,
                        "password": db_pass
                    })
                    
                validated_config.update({
                    "timeout": timeout,
                    "binary_path": binary_path,
                    "host": host,
                    "port": port,
                    "databases": validated_databases,
                    "log_path": log_path,
                    "log_lines": log_lines
                })

            elif coll_name == "redis":
                timeout = coll_val.get("timeout", 5)
                try:
                    timeout = int(timeout)
                    if timeout < 1:
                        raise ValueError
                except (ValueError, TypeError):
                    print("Error: redis 'timeout' must be an integer >= 1", file=sys.stderr)
                    sys.exit(1)
                binary_path = coll_val.get("binary_path")
                host = coll_val.get("host")
                port = coll_val.get("port")
                username = coll_val.get("username", "")
                password = coll_val.get("password", "")
                log_path = coll_val.get("log_path")
                log_lines = coll_val.get("log_lines", 50)
                
                if not isinstance(binary_path, str) or not binary_path:
                    print("Error: redis 'binary_path' must be a non-empty string", file=sys.stderr)
                    sys.exit(1)
                if not isinstance(host, str) or not host:
                    print("Error: redis 'host' must be a non-empty string", file=sys.stderr)
                    sys.exit(1)
                try:
                    port = int(port)
                    if port < 1:
                        raise ValueError
                except (ValueError, TypeError):
                    print("Error: redis 'port' must be an integer >= 1", file=sys.stderr)
                    sys.exit(1)
                if not isinstance(log_path, str) or not log_path:
                    print("Error: redis 'log_path' must be a non-empty string", file=sys.stderr)
                    sys.exit(1)
                try:
                    log_lines = int(log_lines)
                    if log_lines < 1:
                        raise ValueError
                except (ValueError, TypeError):
                    print("Error: redis 'log_lines' must be an integer >= 1", file=sys.stderr)
                    sys.exit(1)
                    
                validated_config.update({
                    "timeout": timeout,
                    "binary_path": binary_path,
                    "host": host,
                    "port": port,
                    "username": username,
                    "password": password,
                    "log_path": log_path,
                    "log_lines": log_lines
                })

            elif coll_name == "system":
                timeout = coll_val.get("timeout", 5)
                try:
                    timeout = int(timeout)
                    if timeout < 1:
                        raise ValueError
                except (ValueError, TypeError):
                    print("Error: system 'timeout' must be an integer >= 1", file=sys.stderr)
                    sys.exit(1)
                hostname_command = coll_val.get("hostname_command")
                os_version_command = coll_val.get("os_version_command")
                uptime_command = coll_val.get("uptime_command")
                cpu_command = coll_val.get("cpu_command")
                memory_command = coll_val.get("memory_command")
                disk_command = coll_val.get("disk_command")
                disk_path = coll_val.get("disk_path", "/")
                disk_threshold = coll_val.get("disk_threshold", 90)
                
                if not isinstance(hostname_command, str) or not hostname_command:
                    print("Error: system 'hostname_command' must be a non-empty string", file=sys.stderr)
                    sys.stderr.flush()
                    sys.exit(1)
                if not isinstance(os_version_command, str) or not os_version_command:
                    print("Error: system 'os_version_command' must be a non-empty string", file=sys.stderr)
                    sys.exit(1)
                if not isinstance(uptime_command, str) or not uptime_command:
                    print("Error: system 'uptime_command' must be a non-empty string", file=sys.stderr)
                    sys.exit(1)
                if not isinstance(cpu_command, str) or not cpu_command:
                    print("Error: system 'cpu_command' must be a non-empty string", file=sys.stderr)
                    sys.exit(1)
                if not isinstance(memory_command, str) or not memory_command:
                    print("Error: system 'memory_command' must be a non-empty string", file=sys.stderr)
                    sys.exit(1)
                if not isinstance(disk_command, str) or not disk_command:
                    print("Error: system 'disk_command' must be a non-empty string", file=sys.stderr)
                    sys.exit(1)
                if not isinstance(disk_path, str) or not disk_path:
                    print("Error: system 'disk_path' must be a non-empty string", file=sys.stderr)
                    sys.exit(1)
                try:
                    disk_threshold = int(disk_threshold)
                    if disk_threshold < 1 or disk_threshold > 100:
                        raise ValueError
                except (ValueError, TypeError):
                    print("Error: system 'disk_threshold' must be an integer between 1 and 100", file=sys.stderr)
                    sys.exit(1)
                    
                validated_config.update({
                    "timeout": timeout,
                    "hostname_command": hostname_command,
                    "os_version_command": os_version_command,
                    "uptime_command": uptime_command,
                    "cpu_command": cpu_command,
                    "memory_command": memory_command,
                    "disk_command": disk_command,
                    "disk_path": disk_path,
                    "disk_threshold": disk_threshold
                })

            elif coll_name == "launchctl":
                timeout = coll_val.get("timeout", 5)
                try:
                    timeout = int(timeout)
                    if timeout < 1:
                        raise ValueError
                except (ValueError, TypeError):
                    print("Error: launchctl 'timeout' must be an integer >= 1", file=sys.stderr)
                    sys.exit(1)
                services = coll_val.get("services")
                if not isinstance(services, list):
                    print("Error: launchctl 'services' must be a list of strings", file=sys.stderr)
                    sys.exit(1)
                for svc in services:
                    if not isinstance(svc, str) or not svc:
                        print("Error: launchctl 'services' list must only contain non-empty strings", file=sys.stderr)
                        sys.exit(1)
                        
                validated_config.update({
                    "timeout": timeout,
                    "services": services
                })

        validated_collectors[coll_name] = validated_config

    notifier_conf = config.get("notifier", {})
    validated_notifier = {}
    if not isinstance(notifier_conf, dict):
        print("Error: 'notifier' configuration must be a dictionary", file=sys.stderr)
        sys.exit(1)
        return
        
    suppression_enabled = notifier_conf.get("suppression_enabled", True)
    if not isinstance(suppression_enabled, bool):
        print("Error: notifier 'suppression_enabled' must be a boolean", file=sys.stderr)
        sys.exit(1)
        return
    validated_notifier["suppression_enabled"] = suppression_enabled
        
    for provider_name, provider_val in notifier_conf.items():
        if provider_name == "suppression_enabled":
            continue
        if not isinstance(provider_val, dict):
            print(f"Error: Notifier provider '{provider_name}' configuration must be a dictionary", file=sys.stderr)
            sys.exit(1)
            return
            
        enabled = provider_val.get("enabled", False)
        if not isinstance(enabled, bool):
            print(f"Error: Notifier provider '{provider_name}' enabled flag must be a boolean", file=sys.stderr)
            sys.exit(1)
            return
            
        validated_provider = {"enabled": enabled}
        
        if provider_name == "telegram":
            bot_token = provider_val.get("bot_token")
            chat_id = provider_val.get("chat_id")
            timeout = provider_val.get("timeout", 5)
            
            if enabled:
                if not isinstance(bot_token, str) or not bot_token:
                    print("Error: telegram 'bot_token' must be a non-empty string when enabled", file=sys.stderr)
                    sys.exit(1)
                    return
                if not isinstance(chat_id, str) or not chat_id:
                    print("Error: telegram 'chat_id' must be a non-empty string when enabled", file=sys.stderr)
                    sys.exit(1)
                    return
            else:
                if bot_token is not None and not isinstance(bot_token, str):
                    print("Error: telegram 'bot_token' must be a string", file=sys.stderr)
                    sys.exit(1)
                    return
                if chat_id is not None and not isinstance(chat_id, str):
                    print("Error: telegram 'chat_id' must be a string", file=sys.stderr)
                    sys.exit(1)
                    return
                    
            try:
                timeout = int(timeout)
                if timeout <= 0:
                    raise ValueError
            except (ValueError, TypeError):
                print("Error: telegram 'timeout' must be an integer greater than zero", file=sys.stderr)
                sys.exit(1)
                return
                
            validated_provider.update({
                "bot_token": bot_token,
                "chat_id": chat_id,
                "timeout": timeout
            })
            
        validated_notifier[provider_name] = validated_provider

    # Build return config dict preserving any optional keys like 'snapshot'
    result_config = {
        "targets": validated_targets,
        "incident": {
            "verification_attempts": verification_attempts,
            "verification_delay": verification_delay
        },
        "collectors": validated_collectors,
        "notifier": validated_notifier
    }
    if "snapshot" in config:
        result_config["snapshot"] = config["snapshot"]
    return result_config
