import sys
import os
from unittest.mock import patch, MagicMock

# Adjust search path to load app modules correctly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.collector import CollectorManager
from app.evidence import CollectorResult
from app.config import load_config

# Helper to validate CollectorResult structure
def assert_collector_result(res: CollectorResult, expected_name: str):
    assert isinstance(res, CollectorResult), "Must be a CollectorResult"
    assert res.collector_name == expected_name, f"Expected name {expected_name}, got {res.collector_name}"
    assert isinstance(res.success, bool), "Success must be a boolean"
    assert isinstance(res.started_at, str), "Started_at must be a string"
    assert isinstance(res.finished_at, str), "Finished_at must be a string"
    assert isinstance(res.duration_ms, float), "Duration_ms must be a float"
    assert res.data is None or isinstance(res.data, dict), "Data must be None or a dict"
    if res.success:
        assert res.error is None, "Error must be None if success is True"
    else:
        assert isinstance(res.error, str), "Error must be a string if success is False"

class MockCompletedProcess:
    def __init__(self, returncode, stdout, stderr):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

def run_tests():
    print("==================================================")
    print("Starting Type 1 Verification for Batch 2 Collectors")
    print("==================================================")

    # ----------------------------------------------------
    # 1. CollectorManager Registration Test
    # ----------------------------------------------------
    print("\n--- 1. Testing CollectorManager Registration ---")
    registered_keys = CollectorManager._registry.keys()
    expected_keys = ["postgres", "redis", "system", "launchctl"]
    for key in expected_keys:
        assert key in registered_keys, f"Collector '{key}' is not registered!"
        print(f"Registration verification for '{key}': OK")

    # ----------------------------------------------------
    # 2. Config Schema Validation Tests
    # ----------------------------------------------------
    print("\n--- 2. Testing Configuration Validation ---")
    
    # Save a temporary valid configuration file to test loader
    temp_config_path = "config/temp_test_config.yaml"
    os.makedirs("config", exist_ok=True)
    with open(temp_config_path, "w") as f:
        f.write("""
targets:
  - name: "Test Target"
    endpoint: "http://localhost:8000"
    interval: 2
    timeout: 3
incident:
  verification_attempts: 2
  verification_delay: 2
collectors:
  postgres:
    enabled: true
    timeout: 5
    binary_path: "pg_isready"
    host: "localhost"
    port: 5432
    username: "postgres"
    dbname: "postgres"
    log_path: "logs/postgres.log"
  redis:
    enabled: true
    timeout: 5
    binary_path: "redis-cli"
    host: "localhost"
    port: 6379
    log_path: "logs/redis.log"
  system:
    enabled: true
    timeout: 5
    hostname_command: "hostname"
    os_version_command: "sw_vers"
    uptime_command: "uptime"
    cpu_command: "sysctl"
    memory_command: "vm_stat"
    disk_command: "df"
    disk_path: "/"
    disk_threshold: 90
  launchctl:
    enabled: true
    timeout: 5
    services:
      - "com.hexa.backend"
""")

    try:
        cfg = load_config(temp_config_path)
        assert "postgres" in cfg["collectors"], "Missing postgres config in output"
        assert cfg["collectors"]["postgres"]["timeout"] == 5
        print("Schema Validation with Valid Config: OK")
    finally:
        if os.path.exists(temp_config_path):
            os.remove(temp_config_path)

    # ----------------------------------------------------
    # 3. PostgreSQL Collector Tests
    # ----------------------------------------------------
    print("\n--- 3. Testing PostgreSQL Collector ---")
    from app.collector.postgres import PostgresCollector
    pg_collector = PostgresCollector("postgres")
    
    pg_valid_config = {
        "timeout": 5,
        "binary_path": "pg_isready",
        "host": "localhost",
        "port": 5432,
        "username": "postgres",
        "dbname": "postgres",
        "password": "pass",
        "log_path": "logs/postgres_nonexistent.log",
        "log_lines": 10
    }

    # PostgreSQL Mock setups
    class MockCursor:
        def __init__(self, simulate_fail=False):
            self.simulate_fail = simulate_fail
            self.last_query = None
        def __enter__(self): return self
        def __exit__(self, exc_type, val, tb): pass
        def execute(self, sql): self.last_query = sql
        def fetchone(self):
            if self.simulate_fail:
                raise Exception("Query error")
            if "pg_stat_activity" in self.last_query:
                return (12,)
            elif "max_connections" in self.last_query:
                return ("150",)
            return (None,)

    class MockConn:
        def __init__(self, simulate_fail=False):
            self.simulate_fail = simulate_fail
        def cursor(self): return MockCursor(self.simulate_fail)
        def close(self): pass

    # Success Path Test
    def mock_pg_success_run(args, **kwargs):
        if "ps" in args[0]:
            return MockCompletedProcess(0, "  PID COMMAND\n 1001 postgres -D data\n", "")
        return MockCompletedProcess(0, "localhost:5432 - accepting connections", "")

    with patch("subprocess.run", side_effect=mock_pg_success_run), \
         patch("psycopg2.connect", return_value=MockConn()):
        res = pg_collector.collect(pg_valid_config)
        assert_collector_result(res, "postgres")
        assert res.success is True
        assert res.data["running"] is True
        assert res.data["active_connections"] == 12
        assert res.data["max_connections"] == 150
        assert res.data["db_query_warning"] is None
        print("Success Path Test: PASSED")

    # Graceful Degradation Path Test (Auth/DB Failure)
    with patch("subprocess.run", side_effect=mock_pg_success_run), \
         patch("psycopg2.connect", side_effect=Exception("Auth failure")):
        res = pg_collector.collect(pg_valid_config)
        assert_collector_result(res, "postgres")
        assert res.success is True
        assert res.data["active_connections"] is None
        assert "Auth failure" in res.data["db_query_warning"]
        print("Graceful Degradation Path Test: PASSED")

    # Framework Failure Path Test (Binary missing)
    def mock_pg_missing_binary(args, **kwargs):
        if "ps" in args[0]:
            return MockCompletedProcess(0, "", "")
        raise FileNotFoundError("[Errno 2] No such file or directory: 'pg_isready'")

    with patch("subprocess.run", side_effect=mock_pg_missing_binary):
        res = pg_collector.collect(pg_valid_config)
        assert_collector_result(res, "postgres")
        assert res.success is False
        assert "No such file or directory" in res.error
        print("Framework Failure Path Test: PASSED")

    # ----------------------------------------------------
    # 4. Redis Collector Tests
    # ----------------------------------------------------
    print("\n--- 4. Testing Redis Collector ---")
    from app.collector.redis import RedisCollector
    redis_collector = RedisCollector("redis")
    
    redis_valid_config = {
        "timeout": 5,
        "binary_path": "redis-cli",
        "host": "localhost",
        "port": 6379,
        "username": "default",
        "password": "pass",
        "log_path": "logs/redis_nonexistent.log",
        "log_lines": 10
    }

    # Success Path Test
    def mock_redis_success_run(args, **kwargs):
        if "ps" in args[0]:
            return MockCompletedProcess(0, "  PID COMMAND\n 2002 redis-server\n", "")
        if "ping" in args:
            return MockCompletedProcess(0, "PONG", "")
        if "info" in args:
            info_data = "redis_version:7.2.4\r\nconnected_clients:3\r\nused_memory_human:1.50M\r\nuptime_in_seconds:86400\r\nrole:master"
            return MockCompletedProcess(0, info_data, "")
        return MockCompletedProcess(1, "", "")

    with patch("subprocess.run", side_effect=mock_redis_success_run):
        res = redis_collector.collect(redis_valid_config)
        assert_collector_result(res, "redis")
        assert res.success is True
        assert res.data["running"] is True
        assert res.data["ping_check"]["stdout"] == "PONG"
        assert res.data["diagnostics"]["redis_version"] == "7.2.4"
        assert res.data["diagnostics"]["connected_clients"] == 3
        assert res.data["diagnostics"]["role"] == "master"
        assert res.data["diagnostics"]["raw_info_warning"] is None
        print("Success Path Test: PASSED")

    # Malformed Output Path Test
    def mock_redis_malformed_run(args, **kwargs):
        if "ps" in args[0]:
            return MockCompletedProcess(0, "  PID COMMAND\n 2002 redis-server\n", "")
        if "ping" in args:
            return MockCompletedProcess(0, "PONG", "")
        if "info" in args:
            # Send invalid metrics format
            info_data = "redis_version:7.2.4\r\nconnected_clients:not_a_number\r\nused_memory_human:1.50M\r\nuptime_in_seconds:\r\nrole:master"
            return MockCompletedProcess(0, info_data, "")
        return MockCompletedProcess(1, "", "")

    with patch("subprocess.run", side_effect=mock_redis_malformed_run):
        res = redis_collector.collect(redis_valid_config)
        assert_collector_result(res, "redis")
        assert res.success is True
        assert res.data["diagnostics"]["connected_clients"] is None
        assert res.data["diagnostics"]["uptime_in_seconds"] is None
        assert res.data["diagnostics"]["redis_version"] == "7.2.4"
        print("Malformed Output Path Test: PASSED")

    # Graceful Degradation Path Test (Auth failure)
    def mock_redis_auth_fail_run(args, **kwargs):
        if "ps" in args[0]:
            return MockCompletedProcess(0, "  PID COMMAND\n 2002 redis-server\n", "")
        if "ping" in args:
            return MockCompletedProcess(1, "NOAUTH Authentication required.", "")
        if "info" in args:
            return MockCompletedProcess(1, "", "NOAUTH Authentication required.")
        return MockCompletedProcess(1, "", "")

    with patch("subprocess.run", side_effect=mock_redis_auth_fail_run):
        res = redis_collector.collect(redis_valid_config)
        assert_collector_result(res, "redis")
        assert res.success is True
        assert res.data["ping_check"]["exit_code"] == 1
        assert "redis-cli info returned exit code 1" in res.data["diagnostics"]["raw_info_warning"]
        print("Graceful Degradation Path Test: PASSED")

    # ----------------------------------------------------
    # 5. System Collector Tests
    # ----------------------------------------------------
    print("\n--- 5. Testing System Collector ---")
    from app.collector.system import SystemCollector
    sys_collector = SystemCollector("system")
    
    sys_valid_config = {
        "timeout": 5,
        "hostname_command": "hostname",
        "os_version_command": "sw_vers",
        "uptime_command": "uptime",
        "cpu_command": "sysctl",
        "memory_command": "vm_stat",
        "disk_command": "df",
        "disk_path": "/",
        "disk_threshold": 90
    }

    # Success Path Test
    def mock_sys_success_run(args, **kwargs):
        cmd = " ".join(args)
        if "hostname" in cmd:
            return MockCompletedProcess(0, "mac-mini.local", "")
        if "sw_vers" in cmd:
            return MockCompletedProcess(0, "macOS 14.5", "")
        if "uptime" in cmd:
            return MockCompletedProcess(0, "up 12 days", "")
        if "sysctl" in cmd:
            return MockCompletedProcess(0, "1.23 1.45 1.50", "")
        if "vm_stat" in cmd:
            return MockCompletedProcess(0, "Pages free: 45678", "")
        if "df" in cmd:
            return MockCompletedProcess(0, "Filesystem Capacity\n/dev/disk1 85%\n", "")
        return MockCompletedProcess(1, "", "")

    with patch("subprocess.run", side_effect=mock_sys_success_run):
        res = sys_collector.collect(sys_valid_config)
        assert_collector_result(res, "system")
        assert res.success is True
        assert res.data["hostname"] == "mac-mini.local"
        assert res.data["os_version"] == "macOS 14.5"
        assert res.data["disk"]["parsed_usage_percent"] == 85
        assert res.data["disk"]["threshold_exceeded"] is False
        print("Success Path Test: PASSED")

    # Disk Threshold Exceeded Test
    def mock_sys_high_disk_run(args, **kwargs):
        cmd = " ".join(args)
        if "hostname" in cmd: return MockCompletedProcess(0, "mac-mini.local", "")
        if "sw_vers" in cmd: return MockCompletedProcess(0, "macOS", "")
        if "uptime" in cmd: return MockCompletedProcess(0, "up", "")
        if "sysctl" in cmd: return MockCompletedProcess(0, "1.0", "")
        if "vm_stat" in cmd: return MockCompletedProcess(0, "Pages", "")
        if "df" in cmd:
            return MockCompletedProcess(0, "Filesystem Capacity\n/dev/disk1 95%\n", "")
        return MockCompletedProcess(1, "", "")

    with patch("subprocess.run", side_effect=mock_sys_high_disk_run):
        res = sys_collector.collect(sys_valid_config)
        assert_collector_result(res, "system")
        assert res.success is True
        assert res.data["disk"]["parsed_usage_percent"] == 95
        assert res.data["disk"]["threshold_exceeded"] is True
        print("Disk Threshold Exceeded Test: PASSED")

    # Malformed Disk Output Test
    def mock_sys_malformed_disk_run(args, **kwargs):
        cmd = " ".join(args)
        if "hostname" in cmd: return MockCompletedProcess(0, "mac-mini", "")
        if "sw_vers" in cmd: return MockCompletedProcess(0, "macOS", "")
        if "uptime" in cmd: return MockCompletedProcess(0, "up", "")
        if "sysctl" in cmd: return MockCompletedProcess(0, "1.0", "")
        if "vm_stat" in cmd: return MockCompletedProcess(0, "Pages", "")
        if "df" in cmd:
            # Missing percentage usage capacity column output
            return MockCompletedProcess(0, "Filesystem Capacity\n/dev/disk1 capacity_unknown\n", "")
        return MockCompletedProcess(1, "", "")

    with patch("subprocess.run", side_effect=mock_sys_malformed_disk_run):
        res = sys_collector.collect(sys_valid_config)
        assert_collector_result(res, "system")
        assert res.success is True
        assert res.data["disk"]["parsed_usage_percent"] is None
        assert res.data["disk"]["threshold_exceeded"] is False
        print("Malformed Disk Output Test: PASSED")

    # ----------------------------------------------------
    # 6. Launchctl Collector Tests
    # ----------------------------------------------------
    print("\n--- 6. Testing Launchctl Collector ---")
    from app.collector.launchctl import LaunchctlCollector
    launch_collector = LaunchctlCollector("launchctl")
    
    launch_valid_config = {
        "timeout": 5,
        "services": [
            "com.hexa.backend",
            "com.apple.Spotlight"
        ]
    }

    # Success Path Test
    def mock_launch_success_run(args, **kwargs):
        if len(args) == 2: # general list command 'launchctl list'
            return MockCompletedProcess(0, "12345 0 com.hexa.backend\n- 0 com.apple.Spotlight\n", "")
        if len(args) == 3: # deep command 'launchctl list <service>'
            return MockCompletedProcess(0, '{\n  "Label" = "com.hexa.backend";\n  "PID" = 12345;\n}', "")
        return MockCompletedProcess(1, "", "")

    with patch("subprocess.run", side_effect=mock_launch_success_run):
        res = launch_collector.collect(launch_valid_config)
        assert_collector_result(res, "launchctl")
        assert res.success is True
        
        backend = res.data["services"]["com.hexa.backend"]
        assert backend["registered"] is True
        assert backend["running"] is True
        assert backend["pid"] == 12345
        assert backend["last_exit_code"] == 0
        assert backend["details"] is not None
        assert backend["details_warning"] is None
        
        spotlight = res.data["services"]["com.apple.Spotlight"]
        assert spotlight["registered"] is True
        assert spotlight["running"] is False
        assert spotlight["pid"] is None
        assert spotlight["last_exit_code"] == 0
        print("Success Path Test: PASSED")

    # Graceful Degradation Path Test (Deep lookup fails for registered but protected service)
    def mock_launch_degraded_run(args, **kwargs):
        if len(args) == 2:
            return MockCompletedProcess(0, "12345 0 com.hexa.backend\n", "")
        if len(args) == 3:
            return MockCompletedProcess(1, "", "Permission Denied")
        return MockCompletedProcess(1, "", "")

    with patch("subprocess.run", side_effect=mock_launch_degraded_run):
        res = launch_collector.collect(launch_valid_config)
        assert_collector_result(res, "launchctl")
        assert res.success is True
        backend = res.data["services"]["com.hexa.backend"]
        assert backend["registered"] is True
        assert backend["details"] is None
        assert "returned exit code 1" in backend["details_warning"]
        print("Graceful Degradation Path Test: PASSED")

    # ----------------------------------------------------
    # Verification Finish
    # ----------------------------------------------------
    print("\n==================================================")
    print("ALL TESTS PASSED SUCCESSFULLY! TYPE 1 VERIFIED")
    print("==================================================")

if __name__ == "__main__":
    run_tests()
