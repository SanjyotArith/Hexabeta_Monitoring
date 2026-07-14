import sys
import os
import yaml
from unittest.mock import patch, MagicMock

# Adjust search path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import load_config
from app.collector.postgres import PostgresCollector
from app.evidence import CollectorResult

class MockCompletedProcess:
    def __init__(self, returncode, stdout, stderr):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

def test_validation():
    print("Configuration Validation ..... ", end="", flush=True)
    
    # Base target structure
    base_config = {
        "targets": [{"name": "T", "endpoint": "http://a", "interval": 1, "timeout": 1}],
        "incident": {"verification_attempts": 1, "verification_delay": 1},
        "collectors": {
            "postgres": {
                "enabled": True,
                "timeout": 5,
                "binary_path": "pg_isready",
                "host": "localhost",
                "port": 5432,
                "log_path": "log.log",
                "log_lines": 50,
                "databases": [] # to be filled
            }
        }
    }
    
    def write_temp_config(postgres_cfg):
        cfg = dict(base_config)
        cfg["collectors"]["postgres"] = postgres_cfg
        with open("config/temp_val_config.yaml", "w") as f:
            yaml.dump(cfg, f)

    try:
        os.makedirs("config", exist_ok=True)
        
        # 1. Valid Configuration
        write_temp_config({
            "enabled": True,
            "timeout": 5,
            "binary_path": "pg_isready",
            "host": "localhost",
            "port": 5432,
            "log_path": "log.log",
            "log_lines": 50,
            "databases": [
                {"name": "loops_db", "username": "user1", "password": "pw1"},
                {"name": "wallet_db", "username": "user2", "password": "pw2"}
            ]
        })
        # Should load successfully
        parsed = load_config("config/temp_val_config.yaml")
        assert len(parsed["collectors"]["postgres"]["databases"]) == 2
        
        # Helper to assert configuration fails
        def assert_validation_fails(config_data):
            write_temp_config(config_data)
            try:
                # Capture standard error print and exit behavior
                with patch("sys.exit") as mock_exit:
                    load_config("config/temp_val_config.yaml")
                    assert mock_exit.called
            except SystemExit:
                pass

        # 2. Missing databases key
        assert_validation_fails({
            "enabled": True,
            "timeout": 5,
            "binary_path": "pg_isready",
            "host": "localhost",
            "port": 5432,
            "log_path": "log.log"
        })

        # 3. Empty databases list
        assert_validation_fails({
            "enabled": True, "timeout": 5, "binary_path": "pg_isready", "host": "localhost", "port": 5432, "log_path": "log.log",
            "databases": []
        })

        # 4. Duplicate database names
        assert_validation_fails({
            "enabled": True, "timeout": 5, "binary_path": "pg_isready", "host": "localhost", "port": 5432, "log_path": "log.log",
            "databases": [
                {"name": "loops_db", "username": "user1", "password": ""},
                {"name": "loops_db", "username": "user2", "password": ""}
            ]
        })

        # 5. Missing database name
        assert_validation_fails({
            "enabled": True, "timeout": 5, "binary_path": "pg_isready", "host": "localhost", "port": 5432, "log_path": "log.log",
            "databases": [
                {"username": "user1", "password": ""}
            ]
        })

        # 6. Missing username
        assert_validation_fails({
            "enabled": True, "timeout": 5, "binary_path": "pg_isready", "host": "localhost", "port": 5432, "log_path": "log.log",
            "databases": [
                {"name": "loops_db", "password": ""}
            ]
        })

        # 7. Missing password field
        assert_validation_fails({
            "enabled": True, "timeout": 5, "binary_path": "pg_isready", "host": "localhost", "port": 5432, "log_path": "log.log",
            "databases": [
                {"name": "loops_db", "username": "user1"}
            ]
        })

        # 8. Non-string values
        assert_validation_fails({
            "enabled": True, "timeout": 5, "binary_path": "pg_isready", "host": "localhost", "port": 5432, "log_path": "log.log",
            "databases": [
                {"name": 1234, "username": "user1", "password": ""}
            ]
        })

        # 9. Invalid database entry type (non-dictionary)
        assert_validation_fails({
            "enabled": True, "timeout": 5, "binary_path": "pg_isready", "host": "localhost", "port": 5432, "log_path": "log.log",
            "databases": ["loops_db"]
        })

        print("PASSED")
    finally:
        if os.path.exists("config/temp_val_config.yaml"):
            os.remove("config/temp_val_config.yaml")

class MockCursor:
    def __init__(self, simulate_fail=False):
        self.simulate_fail = simulate_fail
        self.last_query = None
    def __enter__(self): return self
    def __exit__(self, exc_type, val, tb): pass
    def execute(self, sql): self.last_query = sql
    def fetchone(self):
        if self.simulate_fail:
            raise Exception("Query execution failed")
        if "pg_stat_activity" in self.last_query:
            return (14,)
        elif "max_connections" in self.last_query:
            return ("100",)
        return (None,)

class MockConn:
    def __init__(self, simulate_fail=False):
        self.simulate_fail = simulate_fail
    def cursor(self): return MockCursor(self.simulate_fail)
    def close(self): pass

def run_scenarios():
    pg_collector = PostgresCollector("postgres")
    
    config = {
        "timeout": 5,
        "binary_path": "pg_isready",
        "host": "localhost",
        "port": 5432,
        "databases": [
            {"name": "loops_db", "username": "hexa_user", "password": ""},
            {"name": "wallet_db", "username": "hexa_user", "password": ""}
        ],
        "log_path": "logs/postgres_nonexistent.log",
        "log_lines": 10
    }

    # Setup trackers for subprocess runs
    subprocess_calls = []

    def mock_pg_success_run(args, **kwargs):
        subprocess_calls.append(args)
        if "ps" in args[0]:
            return MockCompletedProcess(0, "  PID COMMAND\n 1001 postgres -D data\n", "")
        return MockCompletedProcess(0, "localhost:5432 - accepting connections", "")

    # Scenario 1: loops_db -> Success, wallet_db -> Success
    print("Scenario 1 ................... ", end="", flush=True)
    subprocess_calls.clear()
    with patch("subprocess.run", side_effect=mock_pg_success_run), \
         patch("psycopg2.connect", return_value=MockConn()):
        res = pg_collector.collect(config)
        assert res.success is True
        assert "loops_db" in res.data["databases"]
        assert "wallet_db" in res.data["databases"]
        
        loops = res.data["databases"]["loops_db"]
        assert loops["active_connections"] == 14
        assert loops["max_connections"] == 100
        assert loops["db_query_warning"] is None
        
        wallet = res.data["databases"]["wallet_db"]
        assert wallet["active_connections"] == 14
        assert wallet["max_connections"] == 100
        assert wallet["db_query_warning"] is None
        
        print("PASSED")

    # Scenario 2: loops_db -> Success, wallet_db -> Failure
    print("Scenario 2 ................... ", end="", flush=True)
    def connect_scenario2(**kwargs):
        dbname = kwargs.get("dbname")
        if dbname == "loops_db":
            return MockConn()
        raise Exception("Authentication failed for wallet_db")

    subprocess_calls.clear()
    with patch("subprocess.run", side_effect=mock_pg_success_run), \
         patch("psycopg2.connect", side_effect=connect_scenario2):
        res = pg_collector.collect(config)
        assert res.success is True
        
        loops = res.data["databases"]["loops_db"]
        assert loops["active_connections"] == 14
        assert loops["db_query_warning"] is None
        
        wallet = res.data["databases"]["wallet_db"]
        assert wallet["active_connections"] is None
        assert "Authentication failed for wallet_db" in wallet["db_query_warning"]
        
        print("PASSED")

    # Scenario 3: loops_db -> Failure, wallet_db -> Success
    print("Scenario 3 ................... ", end="", flush=True)
    def connect_scenario3(**kwargs):
        dbname = kwargs.get("dbname")
        if dbname == "wallet_db":
            return MockConn()
        raise Exception("Authentication failed for loops_db")

    subprocess_calls.clear()
    with patch("subprocess.run", side_effect=mock_pg_success_run), \
         patch("psycopg2.connect", side_effect=connect_scenario3):
        res = pg_collector.collect(config)
        assert res.success is True
        
        loops = res.data["databases"]["loops_db"]
        assert loops["active_connections"] is None
        assert "Authentication failed for loops_db" in loops["db_query_warning"]
        
        wallet = res.data["databases"]["wallet_db"]
        assert wallet["active_connections"] == 14
        assert wallet["db_query_warning"] is None
        
        print("PASSED")

    # Scenario 4: loops_db -> Failure, wallet_db -> Failure
    print("Scenario 4 ................... ", end="", flush=True)
    subprocess_calls.clear()
    with patch("subprocess.run", side_effect=mock_pg_success_run), \
         patch("psycopg2.connect", side_effect=Exception("Database down")):
        res = pg_collector.collect(config)
        assert res.success is True
        
        loops = res.data["databases"]["loops_db"]
        assert loops["active_connections"] is None
        assert "Database down" in loops["db_query_warning"]
        
        wallet = res.data["databases"]["wallet_db"]
        assert wallet["active_connections"] is None
        assert "Database down" in wallet["db_query_warning"]
        
        print("PASSED")

    # Scenario 5: Framework Failure (pg_isready binary missing)
    print("Framework Failure ............ ", end="", flush=True)
    def mock_pg_missing_binary(args, **kwargs):
        if "ps" in args[0]:
            return MockCompletedProcess(0, "  PID COMMAND\n 1001 postgres -D data\n", "")
        raise FileNotFoundError("[Errno 2] No such file or directory: 'pg_isready'")

    with patch("subprocess.run", side_effect=mock_pg_missing_binary):
        res = pg_collector.collect(config)
        assert res.success is False
        assert "No such file or directory" in res.error
        print("PASSED")

    # Regression Checks
    print("Regression ................... ", end="", flush=True)
    subprocess_calls.clear()
    with patch("subprocess.run", side_effect=mock_pg_success_run), \
         patch("psycopg2.connect", return_value=MockConn()):
        res = pg_collector.collect(config)
        
        # 1. Process detection still works
        assert res.data["running"] is True
        assert len(res.data["processes"]) == 1
        
        # 2. pg_isready still executes exactly once
        # Should execute ps and pg_isready (2 calls total)
        isready_calls = [c for c in subprocess_calls if "pg_isready" in c[0]]
        assert len(isready_calls) == 1, f"Expected exactly 1 pg_isready call, got {len(isready_calls)}"
        
        # 3. PostgreSQL log collection is unchanged
        assert isinstance(res.data["log"], list)
        
        # 4. Collector JSON structure is correct
        assert "databases" in res.data
        assert "active_connections" not in res.data
        assert "max_connections" not in res.data
        assert "db_query_warning" not in res.data
        
        print("PASSED")

def main():
    print("==================================================")
    print("Starting Type 1 Verification")
    print("==================================================")
    try:
        test_validation()
        run_scenarios()
        print("\n==================================================")
        print("ALL TESTS PASSED")
        print("TYPE 1 VERIFIED")
        print("==================================================")
    except Exception as e:
        import traceback
        traceback.print_exc()
        try:
            pg_collector = PostgresCollector("postgres")
            config = {
                "timeout": 5, "binary_path": "pg_isready", "host": "localhost", "port": 5432,
                "databases": [{"name": "loops_db", "username": "hexa_user", "password": ""}, {"name": "wallet_db", "username": "hexa_user", "password": ""}],
                "log_path": "logs/postgres_nonexistent.log", "log_lines": 10
            }
            # Re-run and print the actual result dictionary
            with patch("subprocess.run", return_value=MockCompletedProcess(0, "accepting", "")), \
                 patch("psycopg2.connect", side_effect=Exception("DB fail test")):
                res = pg_collector.collect(config)
                print("Last collected res.data:", res.data)
        except Exception:
            pass
        print("\n==================================================")
        print("SOME TESTS FAILED")
        print("==================================================")

if __name__ == "__main__":
    main()
