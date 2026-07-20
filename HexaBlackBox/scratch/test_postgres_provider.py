import sys
import os
import time
import json
import shutil
import subprocess
import re
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

# Adjust search path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.snapshot.models import SnapshotContext, SnapshotProvider, CapturedArtifact, ProviderCaptureResult
from app.snapshot.engine import SnapshotEngine
from app.snapshot.providers.postgres import MacOSPostgreSQLSnapshotProvider, sanitize_query

def setup_clean_evidence_dir(incident_id: str) -> str:
    path = os.path.join("incidents", incident_id)
    if os.path.exists(path):
        shutil.rmtree(path)
    os.makedirs(path)
    return path

def cleanup_evidence_dir(incident_id: str):
    path = os.path.join("incidents", incident_id)
    if os.path.exists(path):
        shutil.rmtree(path)

# Test 1: Connectivity
def test_connectivity():
    print("1. Database Connectivity Checks ........ ", end="", flush=True)
    provider = MacOSPostgreSQLSnapshotProvider()
    
    # 1. Reachable & Unreachable DBs
    context = SnapshotContext(
        incident_id="INC-PG-CONN",
        target_name="Target",
        config={
            "snapshot": {
                "providers": {
                    "postgres": {
                        "databases": [
                            {"name": "db_success", "username": "user1", "password": "pass123"},
                            {"name": "db_fail", "username": "user2", "password": "secret_pass"}
                        ]
                    }
                }
            }
        },
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    
    def fake_connect(host, port, dbname, user, password, connect_timeout, options):
        if dbname == "db_success":
            return MagicMock()
        else:
            raise Exception("Authentication failed for user2")
            
    with patch("psycopg2.connect", side_effect=fake_connect):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
            res = provider.capture(context)
            
    connectivity_art = next(a for a in res.artifacts if a.name == "connectivity.txt")
    assert connectivity_art.status == "PARTIAL"
    assert "Database: db_success | User: user1 | Connection: SUCCESS" in connectivity_art.content
    assert "Database: db_fail | User: user2 | Connection: FAILED" in connectivity_art.content
    
    # Ensure connectivity evidence contains NO passwords or password-bearing DSNs
    assert "pass123" not in connectivity_art.content
    assert "secret_pass" not in connectivity_art.content
    
    print("PASSED")

# Test 2: Multiple Databases
def test_multiple_databases():
    print("2. Multiple DBs Partial Semantics ...... ", end="", flush=True)
    provider = MacOSPostgreSQLSnapshotProvider()
    
    # Multiple configured databases, one unreachable
    context = SnapshotContext(
        incident_id="INC-PG-MDB",
        target_name="Target",
        config={
            "snapshot": {
                "providers": {
                    "postgres": {
                        "databases": [
                            {"name": "db1", "username": "u1", "password": "p1"},
                            {"name": "db2", "username": "u2", "password": "p2"}
                        ]
                    }
                }
            }
        },
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    
    def fake_connect(host, port, dbname, user, password, connect_timeout, options):
        if dbname == "db1":
            return MagicMock() # db1 connects
        raise Exception("Connection refused on db2")
        
    with patch("psycopg2.connect", side_effect=fake_connect):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
            res = provider.capture(context)
            
    # Overall provider status should be PARTIAL since db2 failed but db1 succeeded
    assert res.status == "PARTIAL"
    connectivity_art = next(a for a in res.artifacts if a.name == "connectivity.txt")
    assert connectivity_art.status == "PARTIAL"
    
    print("PASSED")

# Test 3: Connection Metrics
def test_connection_metrics():
    print("3. Connection Metrics & Utilization .... ", end="", flush=True)
    provider = MacOSPostgreSQLSnapshotProvider()
    context = SnapshotContext(
        incident_id="INC-PG-MET",
        target_name="Target",
        config={
            "snapshot": {
                "providers": {
                    "postgres": {
                        "databases": [{"name": "db", "username": "u", "password": "p"}]
                    }
                }
            }
        },
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    
    # 1. Normal State
    mock_cursor = MagicMock()
    # Fetch returns max_connections, total, active, idle, idle in transaction, waiting
    mock_cursor.fetchone.return_value = (100, 45, 10, 30, 5, 2)
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    
    with patch("psycopg2.connect", return_value=mock_conn):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
            res = provider.capture(context)
            
    conns_art = next(a for a in res.artifacts if a.name == "connections.txt")
    assert conns_art.status == "SUCCESS"
    assert "Max Connections: 100" in conns_art.content
    assert "Active Sockets: 10" in conns_art.content
    assert "Connection Utilization: 45.0%" in conns_art.content
    
    # 2. Division-by-Zero Safety (max_connections = 0)
    mock_cursor.fetchone.return_value = (0, 45, 10, 30, 5, 2)
    with patch("psycopg2.connect", return_value=mock_conn):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
            res = provider.capture(context)
    conns_art = next(a for a in res.artifacts if a.name == "connections.txt")
    assert conns_art.status == "SUCCESS"
    assert "Connection Utilization: 0.0%" in conns_art.content
    
    print("PASSED")

# Test 4 & 5: Activity & Query Security
def test_activity_and_query_security():
    print("4 & 5. Activity Row Bounds & Redaction . ", end="", flush=True)
    provider = MacOSPostgreSQLSnapshotProvider()
    context = SnapshotContext(
        incident_id="INC-PG-ACT",
        target_name="Target",
        config={
            "snapshot": {
                "providers": {
                    "postgres": {
                        "databases": [{"name": "db", "username": "u", "password": "p"}],
                        "max_rows": 2,
                        "max_query_length": 50
                    }
                }
            }
        },
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    
    # Raw query containing sensitive details, string literals, and numbers
    raw_query = "SELECT * FROM users WHERE email = 'john.doe@example.com' AND age = 42 AND password = 'secret123' AND token = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature'"
    
    mock_cursor = MagicMock()
    # Mock row output (pid, datname, usename, app_name, client_addr, state, wait_type, wait_event, age, query)
    mock_cursor.fetchall.return_value = [
        (61000, "db", "u", "uvicorn", "127.0.0.1", "active", "IO", "DataFileRead", 5, raw_query),
        (61001, "db", "u", "uvicorn", "127.0.0.1", "active", "IO", "DataFileRead", 6, raw_query)
    ]
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    
    with patch("psycopg2.connect", return_value=mock_conn):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
            res = provider.capture(context)
            
    activity_art = next(a for a in res.artifacts if a.name == "activity.txt")
    assert activity_art.status == "SUCCESS"
    
    # 1. Enforce max_query_length truncation
    assert "[TRUNCATED]" in activity_art.content
    
    # 2. Verify literal and numeric values are sanitized to ?
    # Let's test the sanitization function directly to be precise
    sanitized = sanitize_query(raw_query, 500)
    assert "john.doe@example.com" not in sanitized
    assert "42" not in sanitized
    assert "secret123" not in sanitized
    assert "eyJhbGciOiJIUzI1Ni" not in sanitized
    assert "age = ?" in sanitized
    assert "email = '?'" in sanitized
    assert "password = '<REDACTED>'" in sanitized
    assert "token = '?'" in sanitized
    
    print("PASSED")

# Test 6: Locks
def test_locks():
    print("6. Locks & Blocking Contentions ........ ", end="", flush=True)
    provider = MacOSPostgreSQLSnapshotProvider()
    context = SnapshotContext(
        incident_id="INC-PG-LCK",
        target_name="Target",
        config={
            "snapshot": {
                "providers": {
                    "postgres": {
                        "databases": [{"name": "db", "username": "u", "password": "p"}]
                    }
                }
            }
        },
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    
    mock_cursor = MagicMock()
    # blocked_pid, blocked_statement, blocking_pid, blocking_statement, blocked_mode, blocking_mode
    mock_cursor.fetchall.return_value = [
        (62222, "UPDATE accounts SET balance = balance + 10 WHERE id = 5", 63333, "SELECT * FROM accounts FOR UPDATE", "ExclusiveLock", "ShareLock")
    ]
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    
    with patch("psycopg2.connect", return_value=mock_conn):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
            res = provider.capture(context)
            
    locks_art = next(a for a in res.artifacts if a.name == "locks.txt")
    assert locks_art.status == "SUCCESS"
    assert "62222" in locks_art.content
    assert "63333" in locks_art.content
    # Assert query sanitization
    assert "10" not in locks_art.content
    assert "id = ?" in locks_art.content
    
    print("PASSED")

# Test 7: Long Running Transactions
def test_long_running():
    print("7. Long Running Transactions Filters ... ", end="", flush=True)
    provider = MacOSPostgreSQLSnapshotProvider()
    context = SnapshotContext(
        incident_id="INC-PG-LNG",
        target_name="Target",
        config={
            "snapshot": {
                "providers": {
                    "postgres": {
                        "databases": [{"name": "db", "username": "u", "password": "p"}],
                        "long_running_threshold_seconds": 10
                    }
                }
            }
        },
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    
    mock_cursor = MagicMock()
    # pid, datname, usename, state, age, query
    mock_cursor.fetchall.return_value = [
        (61020, "db", "u", "idle in transaction", 45, "SELECT * FROM logs")
    ]
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    
    with patch("psycopg2.connect", return_value=mock_conn):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
            res = provider.capture(context)
            
    lng_art = next(a for a in res.artifacts if a.name == "long_running.txt")
    assert lng_art.status == "SUCCESS"
    assert "61020" in lng_art.content
    assert "45" in lng_art.content
    
    print("PASSED")

# Test 8: Failure Isolation
def test_failure_isolation():
    print("8. Failure & Query Isolation .......... ", end="", flush=True)
    provider = MacOSPostgreSQLSnapshotProvider()
    context = SnapshotContext(
        incident_id="INC-PG-ISO",
        target_name="Target",
        config={
            "snapshot": {
                "providers": {
                    "postgres": {
                        "databases": [{"name": "db", "username": "u", "password": "p"}]
                    }
                }
            }
        },
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    
    # 1. One diagnostic SQL query fails (e.g. connections) -> other artifacts still SUCCESS
    mock_cursor = MagicMock()
    mock_cursor.execute.side_effect = [
        Exception("pg_stat_activity query failed"), # connections query
        [ (61000, "db", "u", "app", "127.0.0.1", "active", "IO", "Read", 5, "SELECT 1") ], # activity fetch
        [], # locks fetch
        [] # long running fetch
    ]
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    
    with patch("psycopg2.connect", return_value=mock_conn):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
            res = provider.capture(context)
            
    assert res.status == "PARTIAL"
    conns_art = next(a for a in res.artifacts if a.name == "connections.txt")
    activity_art = next(a for a in res.artifacts if a.name == "activity.txt")
    assert conns_art.status == "FAILED"
    assert activity_art.status == "SUCCESS"
    
    # 2. All DB connections fail -> server-level diagnostic failures handled safely
    with patch("psycopg2.connect", side_effect=Exception("Database down")):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
            res = provider.capture(context)
            
    assert res.status == "PARTIAL"
    conns_art = next(a for a in res.artifacts if a.name == "connections.txt")
    assert conns_art.status == "FAILED"
    assert "Skipped system queries" in conns_art.content
    
    print("PASSED")

# Test 9: Timeouts
def test_timeouts():
    print("9. Connection & Query Timeouts ........ ", end="", flush=True)
    provider = MacOSPostgreSQLSnapshotProvider()
    context = SnapshotContext(
        incident_id="INC-PG-TIMEOUT",
        target_name="Target",
        config={
            "snapshot": {
                "providers": {
                    "postgres": {
                        "databases": [{"name": "db", "username": "u", "password": "p"}],
                        "connect_timeout": 4,
                        "query_timeout": 3
                    }
                }
            }
        },
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    
    captured_connect_args = {}
    def fake_connect(host, port, dbname, user, password, connect_timeout, options):
        captured_connect_args["connect_timeout"] = connect_timeout
        captured_connect_args["options"] = options
        return MagicMock()
        
    with patch("psycopg2.connect", side_effect=fake_connect):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
            provider.capture(context)
            
    # Verify connect_timeout and query_timeout dynamically mapped to statement_timeout milliseconds
    assert captured_connect_args["connect_timeout"] == 4
    assert "statement_timeout=3000" in captured_connect_args["options"]
    
    print("PASSED")

# Test 10: OS Process Evidence
def test_os_process():
    print("10. OS Process State Auditing .......... ", end="", flush=True)
    provider = MacOSPostgreSQLSnapshotProvider()
    context = SnapshotContext(
        incident_id="INC-PG-OS",
        target_name="Target",
        config={
            "snapshot": {
                "providers": {
                    "postgres": {
                        "process_matching": ["postgres"]
                    }
                }
            }
        },
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    
    ps_stdout = (
        "  PID  PPID %CPU %MEM COMMAND\n"
        " 1234     1  0.0  0.5 /usr/local/bin/postgres -D /data\n"
        " 1235  1234  0.0  0.2 postgres: writer process\n"
        " 9999     1  0.0  0.0 unrelated process\n"
    )
    
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=ps_stdout, stderr="")
        res = provider.capture(context)
        
    proc_art = next(a for a in res.artifacts if a.name == "postgres_processes.txt")
    assert proc_art.status == "SUCCESS"
    assert "1234" in proc_art.content
    assert "1235" in proc_art.content
    assert "9999" not in proc_art.content
    
    print("PASSED")

# Test 11: Port Evidence
def test_port_evidence():
    print("11. Port Listen filtering (5432) ...... ", end="", flush=True)
    provider = MacOSPostgreSQLSnapshotProvider()
    context = SnapshotContext(
        incident_id="INC-PG-PORT",
        target_name="Target",
        config={
            "snapshot": {
                "providers": {
                    "postgres": {
                        "port": 5432
                    }
                }
            }
        },
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    
    lsof_stdout = "postgres 1234 postgres 5u IPv4 0x... 0t0 TCP *:5432 (LISTEN)\n"
    
    # 1. Local LISTEN port exists
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=lsof_stdout, stderr="")
        res = provider.capture(context)
    port_art = next(a for a in res.artifacts if a.name == "port.txt")
    assert port_art.status == "SUCCESS"
    assert "LISTEN" in port_art.content
    # Assert command arguments contain -sTCP:LISTEN
    mock_run.assert_called_with(["lsof", "-n", "-P", "-i", "tcp:5432", "-sTCP:LISTEN"], capture_output=True, text=True, shell=False, timeout=1.0)
    
    # 2. No Local Listener
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
        res = provider.capture(context)
    port_art = next(a for a in res.artifacts if a.name == "port.txt")
    assert port_art.status == "SUCCESS"
    assert "Listening: false" in port_art.content
    
    print("PASSED")

# Test 12: Observer-Only Safety Audit
def test_observer_only_safety():
    print("12. Observer-Only Safety Code Audit .... ", end="", flush=True)
    postgres_file = "app/snapshot/providers/postgres.py"
    # Terms that must NEVER appear in executable lines
    comment_only_terms = {
        "insert", "update", "delete", "alter", "drop", "create", 
        "vacuum", "analyze", "reindex", "pg_cancel_backend", "pg_terminate_backend"
    }
    # Terms that must not appear anywhere
    banned_anywhere = {"os.system"}
    
    with open(postgres_file, "r") as f:
        content = f.read()
        
    for term in banned_anywhere:
        assert term not in content, f"Banned term '{term}' found in {postgres_file}"
        
    lines = content.splitlines()
    for term in comment_only_terms:
        for idx, line in enumerate(lines):
            # Exclude our SELECT pg_locks JOIN query strings (which contain "join pg_catalog.pg_locks blocked_locks" etc)
            if term in line.lower():
                # Allow lines that are SQL JOIN queries on locks, or comments
                trimmed = line.strip()
                is_comment = trimmed.startswith("#") or trimmed.startswith('"""') or trimmed.startswith("'''")
                is_locks_join = "pg_catalog.pg_locks" in line or "blocked_locks" in line or "blocking_locks" in line
                assert is_comment or is_locks_join, f"Mutating/restricted term '{term}' found in non-comment line {idx+1}: {line}"
                
    print("PASSED")

# Test 13: Subprocess Safety
def test_subprocess_safety():
    print("13. Subprocess Safety Parameters ....... ", end="", flush=True)
    provider = MacOSPostgreSQLSnapshotProvider()
    context = SnapshotContext(
        incident_id="INC-PG-SUB",
        target_name="Target",
        config={},
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
        provider.capture(context)
        
    for call_args in mock_run.call_args_list:
        args, kwargs = call_args
        assert kwargs.get("shell") is False
        assert kwargs.get("timeout") is not None
        
    print("PASSED")

# Test 14: Configuration Deduplication & Fallback
def test_configuration_fallback():
    print("14. Configuration Fallback Precedence .. ", end="", flush=True)
    provider = MacOSPostgreSQLSnapshotProvider()
    context = SnapshotContext(
        incident_id="INC-PG-FALL",
        target_name="Target",
        config={
            "collectors": {
                "postgres": {
                    "host": "fallback_host",
                    "port": 54321,
                    "databases": [{"name": "fallback_db", "username": "fallback_user", "password": "fallback_password"}]
                }
            },
            "snapshot": {
                "providers": {
                    "postgres": {
                        "enabled": True
                    }
                }
            }
        },
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    
    captured_connect_args = {}
    def fake_connect(host, port, dbname, user, password, connect_timeout, options):
        captured_connect_args["host"] = host
        captured_connect_args["port"] = port
        captured_connect_args["dbname"] = dbname
        captured_connect_args["user"] = user
        return MagicMock()
        
    with patch("psycopg2.connect", side_effect=fake_connect):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
            provider.capture(context)
            
    assert captured_connect_args["host"] == "fallback_host"
    assert captured_connect_args["port"] == 54321
    assert captured_connect_args["dbname"] == "fallback_db"
    assert captured_connect_args["user"] == "fallback_user"
    
    print("PASSED")

# Test 15: Storage Structure
def test_storage_structure():
    print("15. Storage & Manifest Integration ..... ", end="", flush=True)
    SnapshotEngine._providers = []
    p = MacOSPostgreSQLSnapshotProvider()
    SnapshotEngine.register_provider(p)
    
    incident_id = "INC-PG-STOR"
    setup_clean_evidence_dir(incident_id)
    
    config = {
        "snapshot": {
            "providers": {
                "postgres": {
                    "enabled": True,
                    "databases": [{"name": "db", "username": "u", "password": "p"}]
                }
            }
        }
    }
    
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = (100, 5, 2, 3, 0, 0)
    mock_cursor.fetchall.return_value = []
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    
    try:
        with patch("psycopg2.connect", return_value=mock_conn):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="output", stderr="")
                SnapshotEngine.run(incident_id, "Target", config)
                
        evidence_dir = os.path.join("incidents", incident_id, "evidence")
        postgres_dir = os.path.join(evidence_dir, "postgres")
        
        # Verify physical file existence
        assert os.path.isfile(os.path.join(evidence_dir, "manifest.json"))
        assert os.path.isfile(os.path.join(postgres_dir, "connectivity.txt"))
        assert os.path.isfile(os.path.join(postgres_dir, "connections.txt"))
        assert os.path.isfile(os.path.join(postgres_dir, "activity.txt"))
        assert os.path.isfile(os.path.join(postgres_dir, "locks.txt"))
        assert os.path.isfile(os.path.join(postgres_dir, "long_running.txt"))
        assert os.path.isfile(os.path.join(postgres_dir, "postgres_processes.txt"))
        assert os.path.isfile(os.path.join(postgres_dir, "port.txt"))
        assert os.path.isfile(os.path.join(postgres_dir, "metadata.json"))
        
    finally:
        cleanup_evidence_dir(incident_id)
        
    print("PASSED")

def main():
    print("==================================================")
    print("Starting Type 1 Verification (Milestone 9 - Batch 4)")
    print("==================================================")
    try:
        test_connectivity()
        test_multiple_databases()
        test_connection_metrics()
        test_activity_and_query_security()
        test_locks()
        test_long_running()
        test_failure_isolation()
        test_timeouts()
        test_os_process()
        test_port_evidence()
        test_observer_only_safety()
        test_subprocess_safety()
        test_configuration_fallback()
        test_storage_structure()
        print("\n==================================================")
        print("ALL CHECKS PASSED")
        print("TYPE 1 VERIFIED")
        print("==================================================")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print("\n==================================================")
        print("SOME CHECKS FAILED")
        print("==================================================")

if __name__ == "__main__":
    main()
