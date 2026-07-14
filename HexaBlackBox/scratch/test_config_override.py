import sys
import os
import yaml
import shutil
from unittest.mock import patch, MagicMock

# Adjust search path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import load_config

def setup_temp_dir():
    os.makedirs("config_test_override", exist_ok=True)
    
    # Base config.yaml template
    base_config = {
        "targets": [{"name": "TestTarget", "endpoint": "http://localhost:8000", "interval": 10}],
        "incident": {"verification_attempts": 2, "verification_delay": 5},
        "collectors": {
            "postgres": {
                "enabled": False,
                "timeout": 5,
                "binary_path": "/usr/bin/pg_isready",
                "host": "localhost",
                "port": 5432,
                "databases": [
                    {"name": "loops_db", "username": "user", "password": ""},
                    {"name": "wallet_db", "username": "user", "password": ""}
                ],
                "log_path": "/var/log/postgres.log",
                "log_lines": 50
            },
            "redis": {
                "enabled": False,
                "timeout": 5,
                "binary_path": "redis-cli",
                "host": "localhost",
                "port": 6379,
                "username": "",
                "password": "",
                "log_path": "/var/log/redis.log",
                "log_lines": 50
            },
            "system": {
                "enabled": False,
                "timeout": 5,
                "hostname_command": "hostname",
                "os_version_command": "sw_vers",
                "uptime_command": "uptime",
                "cpu_command": "sysctl -n vm.loadavg",
                "memory_command": "vm_stat",
                "disk_command": "df -h",
                "disk_path": "/",
                "disk_threshold": 90
            },
            "launchctl": {
                "enabled": False,
                "timeout": 5,
                "services": ["com.apple.nginx"]
            }
        }
    }
    
    with open("config_test_override/config.yaml", "w", encoding="utf-8") as f:
        yaml.dump(base_config, f)

def clean_temp_dir():
    if os.path.exists("config_test_override"):
        shutil.rmtree("config_test_override")

def run_tests():
    print("==================================================")
    print("Starting Type 1 Verification")
    print("==================================================")
    
    results = {
        "No Local Config": False,
        "Single Override": False,
        "Multiple Overrides": False,
        "Nested Override": False,
        "Malformed YAML": False,
        "Validation After Merge": False,
        "Recursive Merge": False,
        "List Replacement": False,
        "Regression": False
    }

    # 1. No config.local.yaml exists
    try:
        setup_temp_dir()
        config = load_config("config_test_override/config.yaml")
        assert config["collectors"]["postgres"]["enabled"] is False
        assert config["collectors"]["redis"]["enabled"] is False
        results["No Local Config"] = True
    except Exception as e:
        import traceback
        traceback.print_exc()
    finally:
        clean_temp_dir()

    # 2. Single Override
    try:
        setup_temp_dir()
        local_cfg = {
            "collectors": {
                "postgres": {
                    "enabled": True
                }
            }
        }
        with open("config_test_override/config.local.yaml", "w") as f:
            yaml.dump(local_cfg, f)
            
        config = load_config("config_test_override/config.yaml")
        assert config["collectors"]["postgres"]["enabled"] is True
        assert config["collectors"]["redis"]["enabled"] is False
        results["Single Override"] = True
    except Exception as e:
        import traceback
        traceback.print_exc()
    finally:
        clean_temp_dir()

    # 3. Multiple Overrides
    try:
        setup_temp_dir()
        local_cfg = {
            "collectors": {
                "postgres": {"enabled": True},
                "redis": {"enabled": True},
                "system": {"enabled": True},
                "launchctl": {"enabled": True}
            }
        }
        with open("config_test_override/config.local.yaml", "w") as f:
            yaml.dump(local_cfg, f)
            
        config = load_config("config_test_override/config.yaml")
        assert config["collectors"]["postgres"]["enabled"] is True
        assert config["collectors"]["redis"]["enabled"] is True
        assert config["collectors"]["system"]["enabled"] is True
        assert config["collectors"]["launchctl"]["enabled"] is True
        results["Multiple Overrides"] = True
    except Exception as e:
        import traceback
        traceback.print_exc()
    finally:
        clean_temp_dir()

    # 4. Nested Override
    try:
        setup_temp_dir()
        local_cfg = {
            "collectors": {
                "postgres": {
                    "enabled": True,
                    "host": "127.0.0.1"
                }
            }
        }
        with open("config_test_override/config.local.yaml", "w") as f:
            yaml.dump(local_cfg, f)
            
        config = load_config("config_test_override/config.yaml")
        assert config["collectors"]["postgres"]["host"] == "127.0.0.1"
        # Confirm untouched sibling values remain
        assert config["collectors"]["postgres"]["port"] == 5432
        assert config["collectors"]["postgres"]["enabled"] is True
        results["Nested Override"] = True
    except Exception as e:
        import traceback
        traceback.print_exc()
    finally:
        clean_temp_dir()

    # 5. Malformed config.local.yaml
    try:
        setup_temp_dir()
        with open("config_test_override/config.local.yaml", "w") as f:
            f.write("collectors:\n  postgres:\n    enabled: : : invalid_yaml")
            
        with patch("sys.exit") as mock_exit:
            load_config("config_test_override/config.yaml")
            assert mock_exit.called
            
        results["Malformed YAML"] = True
    except Exception as e:
        import traceback
        traceback.print_exc()
    finally:
        clean_temp_dir()

    # 6. Validation after merge
    try:
        setup_temp_dir()
        local_cfg = {
            "collectors": {
                "postgres": {
                    "enabled": True,
                    "timeout": -1  # Invalid timeout value
                }
            }
        }
        with open("config_test_override/config.local.yaml", "w") as f:
            yaml.dump(local_cfg, f)
            
        with patch("sys.exit") as mock_exit:
            load_config("config_test_override/config.yaml")
            assert mock_exit.called
            
        results["Validation After Merge"] = True
    except Exception as e:
        import traceback
        traceback.print_exc()
    finally:
        clean_temp_dir()

    # 7. Recursive Merge
    try:
        setup_temp_dir()
        local_cfg = {
            "collectors": {
                "postgres": {
                    "enabled": True
                }
            }
        }
        with open("config_test_override/config.local.yaml", "w") as f:
            yaml.dump(local_cfg, f)
            
        config = load_config("config_test_override/config.yaml")
        assert config["collectors"]["postgres"]["enabled"] is True
        assert config["collectors"]["postgres"]["timeout"] == 5
        results["Recursive Merge"] = True
    except Exception as e:
        import traceback
        traceback.print_exc()
    finally:
        clean_temp_dir()

    # 8. List replacement behavior
    try:
        setup_temp_dir()
        local_cfg = {
            "collectors": {
                "postgres": {
                    "enabled": True,
                    "databases": [
                        {"name": "loops_db", "username": "user", "password": ""}
                    ]
                }
            }
        }
        with open("config_test_override/config.local.yaml", "w") as f:
            yaml.dump(local_cfg, f)
            
        config = load_config("config_test_override/config.yaml")
        # Final merged configuration contains ONLY loops_db (list replacement)
        dbs = config["collectors"]["postgres"]["databases"]
        assert len(dbs) == 1
        assert dbs[0]["name"] == "loops_db"
        results["List Replacement"] = True
    except Exception as e:
        import traceback
        traceback.print_exc()
    finally:
        clean_temp_dir()

    # 9. Regression Checks
    try:
        # Load from core production config file location (should work exactly as today)
        config = load_config("config/config.yaml")
        assert config is not None
        assert "targets" in config
        results["Regression"] = True
    except Exception as e:
        import traceback
        traceback.print_exc()

    # Output results
    print("\n--------------------------------------------------")
    for test_name, passed in results.items():
        dots = "." * (29 - len(test_name))
        status = "PASSED" if passed else "FAILED"
        print(f"{test_name} {dots} {status}")
    print("--------------------------------------------------")
    
    all_passed = all(results.values())
    if all_passed:
        print("\n==================================================")
        print("ALL TESTS PASSED")
        print("TYPE 1 VERIFIED")
        print("==================================================")
    else:
        print("\n==================================================")
        print("SOME TESTS FAILED")
        print("==================================================")

if __name__ == "__main__":
    run_tests()
