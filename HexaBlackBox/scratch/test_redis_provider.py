import sys
import os
import time
import json
import shutil
import subprocess
import re
import yaml
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

# Adjust search path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.snapshot.models import SnapshotContext, CapturedArtifact, ProviderCaptureResult
from app.snapshot.engine import SnapshotEngine
from app.snapshot.providers.redis import MacOSRedisSnapshotProvider, _token_match_process

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

# Test 1: Process Evidence
def test_processes():
    print("1. Process Evidence Verification ....... ", end="", flush=True)
    provider = MacOSRedisSnapshotProvider()
    
    ps_stdout = (
        "  PID  PPID  %CPU  %MEM COMMAND\n"
        " 3000   100   0.1   0.2 redis-server *:6379\n"
        " 3001   100   0.0   0.1 /opt/notaredis-server/helper\n"
        " 3002   100   0.0   0.1 /opt/homebrew/bin/redis-server-helper\n"
        " 3003   100   0.0   0.1 redis-server\n"
    )
    
    context = SnapshotContext(
        incident_id="INC-REDIS-PROC",
        target_name="Target",
        config={},
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=ps_stdout, stderr="")
        res = provider.capture(context)
        
    proc_art = next(a for a in res.artifacts if a.name == "redis_processes.txt")
    assert proc_art.status == "SUCCESS"
    assert "3000" in proc_art.content
    assert "3003" in proc_art.content
    assert "3001" not in proc_art.content
    assert "3002" not in proc_art.content
    
    print("PASSED")

# Test 2: Port Listener
def test_ports():
    print("2. Port Listener Verification .......... ", end="", flush=True)
    provider = MacOSRedisSnapshotProvider()
    
    context = SnapshotContext(
        incident_id="INC-REDIS-PORT",
        target_name="Target",
        config={},
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    
    # 1. Listener found
    lsof_stdout = "redis-ser 3000 redis    4u  IPv4 0xabcdef123      0t0  TCP *:6379 (LISTEN)\n"
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=lsof_stdout, stderr="")
        res = provider.capture(context)
    port_art = next(a for a in res.artifacts if a.name == "port.txt")
    assert port_art.status == "SUCCESS"
    assert "3000" in port_art.content
    assert "LISTEN" in port_art.content
    
    # 2. No listener
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
        res = provider.capture(context)
    port_art = next(a for a in res.artifacts if a.name == "port.txt")
    assert port_art.status == "SUCCESS"
    assert "Listening: false" in port_art.content
    assert "Listener: none" in port_art.content
    
    print("PASSED")

# Test 3: Connectivity
def test_connectivity():
    print("3. Connectivity PING Checks ............ ", end="", flush=True)
    provider = MacOSRedisSnapshotProvider()
    
    context = SnapshotContext(
        incident_id="INC-REDIS-CONN",
        target_name="Target",
        config={},
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    
    # 1. SUCCESS
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="PONG\n", stderr="")
        res = provider.capture(context)
    conn_art = next(a for a in res.artifacts if a.name == "connectivity.txt")
    assert conn_art.status == "SUCCESS"
    assert "Connection: SUCCESS" in conn_art.content
    assert "Response: PONG" in conn_art.content
    
    # 2. Connection refused
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Could not connect to Redis at 127.0.0.1:6379: Connection refused")
        res = provider.capture(context)
    conn_art = next(a for a in res.artifacts if a.name == "connectivity.txt")
    assert conn_art.status == "SUCCESS"
    assert "Connection: FAILED" in conn_art.content
    assert "Connection refused" in conn_art.content
    
    print("PASSED")

# Test 4: Authentication Security
def test_auth_security():
    print("4. Authentication Security ............. ", end="", flush=True)
    provider = MacOSRedisSnapshotProvider()
    
    secret_password = "TYPE1_SUPER_SECRET_REDIS_PASSWORD"
    context = SnapshotContext(
        incident_id="INC-REDIS-AUTH",
        target_name="Target",
        config={
            "snapshot": {
                "providers": {
                    "redis": {
                        "password": secret_password
                    }
                }
            }
        },
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    
    # Run capture with mock runs
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="PONG\n", stderr="")
        res = provider.capture(context)
        
        # Verify REDISCLI_AUTH env was passed
        passed_env = mock_run.call_args[1].get("env", {})
        assert passed_env.get("REDISCLI_AUTH") == secret_password
        
        # Verify the password was NOT passed in command arguments
        for call in mock_run.call_args_list:
            args = call[0][0]
            for arg in args:
                assert secret_password not in str(arg)
                
    # Verify the password does not appear in any artifact contents
    for art in res.artifacts:
        assert secret_password not in art.content
        
    print("PASSED")

# Test 5: Info sections and operation diagnostics
def test_info_sections():
    print("5. INFO Operational Statistics ......... ", end="", flush=True)
    provider = MacOSRedisSnapshotProvider()
    
    context = SnapshotContext(
        incident_id="INC-REDIS-INFO",
        target_name="Target",
        config={},
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    
    info_output = (
        "# Server\n"
        "redis_version:7.0.0\n"
        "# Clients\n"
        "connected_clients:5\n"
        "# Memory\n"
        "used_memory:1048576\n"
        "# Stats\n"
        "total_commands_processed:5000\n"
        "# Replication\n"
        "role:master\n"
        "# Keyspace\n"
        "db0:keys=100,expires=5\n"
    )
    
    def fake_run(args, **kwargs):
        cmd = " ".join(args)
        if "PING" in cmd:
            return MagicMock(returncode=0, stdout="PONG\n", stderr="")
        elif "INFO" in cmd:
            return MagicMock(returncode=0, stdout=info_output, stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")
        
    with patch("subprocess.run", side_effect=fake_run):
        res = provider.capture(context)
        
    info_art = next(a for a in res.artifacts if a.name == "info.txt")
    assert info_art.status == "SUCCESS"
    assert "redis_version" in info_art.content
    assert "role:master" in info_art.content
    assert "connected_clients" not in info_art.content  # Section excluded from info.txt
    
    mem_art = next(a for a in res.artifacts if a.name == "memory.txt")
    assert mem_art.status == "SUCCESS"
    assert "used_memory" in mem_art.content
    assert "redis_version" not in mem_art.content
    
    client_art = next(a for a in res.artifacts if a.name == "clients.txt")
    assert client_art.status == "SUCCESS"
    assert "connected_clients:5" in client_art.content
    assert "CLIENT LIST" not in client_art.content  # Check CLIENT LIST not executed
    
    print("PASSED")

# Test 6: Slowlog Redaction Security
def test_slowlog_redaction():
    print("6. Slowlog Redaction Security .......... ", end="", flush=True)
    provider = MacOSRedisSnapshotProvider()
    
    secrets = [
        "TYPE1_SLOWLOG_VAL_12345",
        "TYPE1_RANDOM_SECRET_VALUE_98765",
        "supersecret",
        "abc123",
        "eyJheader.payload.signature",
        "Bearer secret-token-here"
    ]
    
    # Mock redis slowlog output with diverse sensitive arguments
    slowlog_raw = (
        "1) 1) (integer) 1\n"
        "   2) (integer) 1629812345\n"
        "   3) (integer) 12431\n"
        "   4) 1) \"AUTH\"\n"
        "      2) \"" + secrets[2] + "\"\n"
        "2) 1) (integer) 2\n"
        "   2) (integer) 1629812346\n"
        "   3) (integer) 15000\n"
        "   4) 1) \"SET\"\n"
        "      2) \"user:1:password\"\n"
        "      3) \"" + secrets[0] + "\"\n"
        "3) 1) (integer) 3\n"
        "   2) (integer) 1629812347\n"
        "   3) (integer) 9900\n"
        "   4) 1) \"SET\"\n"
        "      2) \"completely_innocent_key\"\n"
        "      3) \"" + secrets[1] + "\"\n"
        "4) 1) (integer) 4\n"
        "   2) (integer) 1629812348\n"
        "   3) (integer) 8500\n"
        "   4) 1) \"SET\"\n"
        "      2) \"api_token\"\n"
        "      3) \"" + secrets[3] + "\"\n"
        "5) 1) (integer) 5\n"
        "   2) (integer) 1629812349\n"
        "   3) (integer) 12000\n"
        "   4) 1) \"SET\"\n"
        "      2) \"jwt\"\n"
        "      3) \"" + secrets[4] + "\"\n"
        "6) 1) (integer) 6\n"
        "   2) (integer) 1629812350\n"
        "   3) (integer) 7300\n"
        "   4) 1) \"SET\"\n"
        "      2) \"authorization\"\n"
        "      3) \"" + secrets[5] + "\"\n"
    )
    
    context = SnapshotContext(
        incident_id="INC-REDIS-SLOW",
        target_name="Target",
        config={},
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    
    def fake_run(args, **kwargs):
        cmd = " ".join(args)
        if "PING" in cmd:
            return MagicMock(returncode=0, stdout="PONG\n", stderr="")
        elif "SLOWLOG" in cmd:
            return MagicMock(returncode=0, stdout=slowlog_raw, stderr="")
        elif "INFO" in cmd:
            return MagicMock(returncode=0, stdout="", stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")
        
    with patch("subprocess.run", side_effect=fake_run):
        res = provider.capture(context)
        
    slow_art = next(a for a in res.artifacts if a.name == "slowlog.txt")
    assert slow_art.status == "SUCCESS"
    
    # Verify that NONE of the secret arguments leaked to the file
    for s in secrets:
        if s in slow_art.content:
            raise AssertionError(f"Security Bug: Slowlog secret '{s}' leaked to disk unredacted!")
            
    # Also verify that key names like 'completely_innocent_key' or 'user:1:password' are also redacted
    assert "completely_innocent_key" not in slow_art.content
    assert "user:1:password" not in slow_art.content
    assert "api_token" not in slow_art.content
    
    print("PASSED")

# Test 7: Static Code Audit
def test_static_code_audit():
    print("7. Observer-Only Static Audit .......... ", end="", flush=True)
    
    provider_file = os.path.abspath(os.path.join(os.path.dirname(__file__), "../app/snapshot/providers/redis.py"))
    with open(provider_file, "r", encoding="utf-8") as f:
        code = f.read()
        
    # Check forbidden mutating commands
    mutating_commands = [
        "SET", "DEL", "UNLINK", "FLUSHDB", "FLUSHALL", "CONFIG SET", "SHUTDOWN",
        "CLIENT KILL", "SCRIPT FLUSH", "FUNCTION DELETE", "ACL SETUSER", "REPLICAOF",
        "SLAVEOF", "MIGRATE", "RESTORE", "EXPIRE", "PEXPIRE", "RENAME"
    ]
    
    # Parse executions. Since the list `mutating_commands` itself exists, we check if
    # the provider executes them in cmd lists.
    for cmd in mutating_commands:
        # Verify not executed, i.e. not in subprocess calls
        pattern = rf'run_redis_cmd\(\s*\[\s*"{cmd}"'
        assert not re.search(pattern, code, re.IGNORECASE), f"Mutating command {cmd} is executed!"
        
    assert "shell=True" not in code
    print("PASSED")

# Test 8: End to End Snapshot Engine Integration
def test_engine_integration():
    print("8. Snapshot Engine E2E Integration ..... ", end="", flush=True)
    
    incident_id = "INC-REDIS-E2E"
    setup_clean_evidence_dir(incident_id)
    
    SnapshotEngine.register_provider(MacOSRedisSnapshotProvider())
    
    config = {
        "collectors": {
            "redis": {
                "enabled": True,
                "host": "localhost",
                "port": 6379
            }
        },
        "snapshot": {
            "providers": {
                "redis": {
                    "enabled": True,
                    "binary_path": "redis-cli"
                }
            }
        }
    }
    
    try:
        def fake_run(args, **kwargs):
            cmd = " ".join(args)
            if "ps" in cmd:
                return MagicMock(returncode=0, stdout="  PID  PPID  %CPU  %MEM COMMAND\n 3000   100   0.0   0.0 redis-server\n", stderr="")
            elif "lsof" in cmd:
                return MagicMock(returncode=0, stdout="redis-ser 3000 TCP *:6379 (LISTEN)", stderr="")
            elif "PING" in cmd:
                return MagicMock(returncode=0, stdout="PONG\n", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")
            
        prov_dir = f"incidents/{incident_id}/evidence/redis"
        with patch("subprocess.run", side_effect=fake_run):
            manifest = SnapshotEngine.run(incident_id, "Redis", config)
            # Find the actual result to print artifacts
            print("\nDEBUG MANIFEST:", json.dumps(manifest, indent=2))
            meta_path = os.path.join(prov_dir, "metadata.json")
            if os.path.exists(meta_path):
                with open(meta_path, "r") as f:
                    print("DEBUG METADATA:", f.read())
            # Let's inspect the files in the directory
            print("DIRECTORY CONTENTS:", os.listdir(prov_dir) if os.path.exists(prov_dir) else "Directory does not exist")
        assert os.path.exists(prov_dir)
        assert os.path.exists(os.path.join(prov_dir, "redis_processes.txt"))
        assert os.path.exists(os.path.join(prov_dir, "port.txt"))
        assert os.path.exists(os.path.join(prov_dir, "connectivity.txt"))
        assert os.path.exists(os.path.join(prov_dir, "metadata.json"))
        
        cf_res = next(r for r in manifest["results"] if r["provider_name"] == "redis")
        assert cf_res["status"] == "SUCCESS"
        
    finally:
        cleanup_evidence_dir(incident_id)
        
    print("PASSED")

def main():
    print("==================================================")
    print("Starting Type 1 Verification (Milestone 9 - Batch 6)")
    print("==================================================")
    
    try:
        test_processes()
        test_ports()
        test_connectivity()
        test_auth_security()
        test_info_sections()
        test_slowlog_redaction()
        test_static_code_audit()
        test_engine_integration()
        
        print("\n==================================================")
        print("ALL CHECKS PASSED")
        print("TYPE 1 VERIFIED")
        print("==================================================")
    except AssertionError as e:
        print("\n==================================================")
        print("VERIFICATION FAILED")
        print("==================================================")
        raise e

if __name__ == "__main__":
    main()
