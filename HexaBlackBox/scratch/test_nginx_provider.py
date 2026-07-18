import sys
import os
import time
import json
import shutil
import subprocess
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

# Adjust search path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.snapshot.models import SnapshotContext, SnapshotProvider, CapturedArtifact, ProviderCaptureResult
from app.snapshot.engine import SnapshotEngine
from app.snapshot.providers.nginx import MacOSNginxSnapshotProvider
from app.snapshot.redaction import redact_content

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

# Test 1: Log Evidence
def test_log_evidence():
    print("1. Log Evidence Capture & Handling .... ", end="", flush=True)
    access_log = "temp_access.log"
    error_log = "temp_error.log"
    
    # 1. Bounded logs & custom messages for empty files
    with open(access_log, "w", encoding="utf-8") as f:
        f.write("log line 1\nlog line 2\n")
    with open(error_log, "w", encoding="utf-8") as f:
        f.write("") # Empty log file
        
    provider = MacOSNginxSnapshotProvider()
    context = SnapshotContext(
        incident_id="INC-NG1",
        target_name="Target",
        config={
            "snapshot": {
                "providers": {
                    "nginx": {
                        "logs": {
                            "access_log_path": access_log,
                            "error_log_path": error_log,
                            "max_lines": 500,
                            "max_bytes": 10000
                        }
                    }
                }
            }
        },
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="clean output", stderr="")
        res = provider.capture(context)
        
    access_art = next(a for a in res.artifacts if a.name == "access.log")
    error_art = next(a for a in res.artifacts if a.name == "error.log")
    
    # Access log is captured
    assert access_art.status == "SUCCESS"
    assert "log line 2" in access_art.content
    
    # Empty error log creates explicit physical evidence message
    assert error_art.status == "SUCCESS"
    assert error_art.content == "Log file existed but was empty at snapshot time."
    assert error_art.bytes_captured > 0
    
    # Clean up logs
    for log in [access_log, error_log]:
        if os.path.exists(log):
            os.remove(log)
            
    # 2. Missing logs handled safely
    context.config["snapshot"]["providers"]["nginx"]["logs"]["access_log_path"] = "missing_access.log"
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="clean", stderr="")
        res = provider.capture(context)
        
    access_art = next(a for a in res.artifacts if a.name == "access.log")
    assert access_art.status == "FAILED"
    assert "File not found" in access_art.error_message
    
    print("PASSED")

# Test 2: Redaction
def test_redaction():
    print("2. Log Redaction Flow .................. ", end="", flush=True)
    access_log = "temp_access.log"
    error_log = "temp_error.log"
    
    secrets = (
        "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature\n"
        "Cookie: sess=12345\n"
        "URL: /api?token=secret_key\n"
    )
    
    with open(access_log, "w", encoding="utf-8") as f:
        f.write(secrets)
    with open(error_log, "w", encoding="utf-8") as f:
        f.write(secrets)
        
    SnapshotEngine._providers = []
    p = MacOSNginxSnapshotProvider()
    SnapshotEngine.register_provider(p)
    
    config = {
        "snapshot": {
            "providers": {
                "nginx": {
                    "enabled": True,
                    "logs": {
                        "access_log_path": access_log,
                        "error_log_path": error_log
                    }
                }
            }
        }
    }
    
    incident_id = "INC-NG-REDACT"
    setup_clean_evidence_dir(incident_id)
    
    try:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="clean", stderr="")
            SnapshotEngine.run(incident_id, "Target", config)
            
        evidence_dir = os.path.join("incidents", incident_id, "evidence")
        nginx_dir = os.path.join(evidence_dir, "nginx")
        manifest_file = os.path.join(evidence_dir, "manifest.json")
        metadata_file = os.path.join(nginx_dir, "metadata.json")
        access_log_evidence = os.path.join(nginx_dir, "access.log")
        
        for path in [manifest_file, metadata_file, access_log_evidence]:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
                assert "secret_key" not in content
                assert "eyJhbGciOiJIUzI1Ni" not in content
                assert "sess=12345" not in content
                
    finally:
        cleanup_evidence_dir(incident_id)
        for log in [access_log, error_log]:
            if os.path.exists(log):
                os.remove(log)
                
    print("PASSED")

# Test 3: Process Evidence
def test_process_evidence():
    print("3. Process Evidence Parsing ............ ", end="", flush=True)
    provider = MacOSNginxSnapshotProvider()
    context = SnapshotContext(
        incident_id="INC-NG-PROC",
        target_name="Target",
        config={
            "snapshot": {
                "providers": {
                    "nginx": {
                        "process": {
                            "expected_command_contains": ["nginx"]
                        }
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
        "  500     1  0.0  0.5 nginx: master process /usr/sbin/nginx\n"
        "  501   500  0.1  0.8 nginx: worker process\n"
        "  502   500  0.1  0.8 nginx: worker process\n"
        " 9999     1  0.1  0.2 unrelated process\n"
    )
    
    # 1. Process Present
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=ps_stdout, stderr="")
        res = provider.capture(context)
        
    proc_art = next(a for a in res.artifacts if a.name == "processes.txt")
    assert proc_art.status == "SUCCESS"
    assert "500" in proc_art.content
    assert "501" in proc_art.content
    assert "502" in proc_art.content
    assert "unrelated" not in proc_art.content
    
    # 2. Process Absent
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="  PID  PPID %CPU %MEM COMMAND\n9999 1 0.0 0.0 unrelated\n", stderr="")
        res = provider.capture(context)
    proc_art = next(a for a in res.artifacts if a.name == "processes.txt")
    assert proc_art.status == "SUCCESS"
    assert "unrelated" not in proc_art.content
    
    print("PASSED")

# Test 4: Port Evidence
def test_port_evidence():
    print("4. Port Evidence Parsing .............. ", end="", flush=True)
    provider = MacOSNginxSnapshotProvider()
    context = SnapshotContext(
        incident_id="INC-NG-PORT",
        target_name="Target",
        config={
            "snapshot": {
                "providers": {
                    "nginx": {
                        "network": {
                            "ports": [80, 443]
                        }
                    }
                }
            }
        },
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    
    # Mock lsof for ports 80 and 443
    # 80 is listening, 443 is down
    lsof_80 = "nginx 500 root 6u IPv4 0x... 0t0 TCP *:80 (LISTEN)\n"
    
    def fake_run(cmd, **kwargs):
        if "80" in cmd[-1]:
            return MagicMock(returncode=0, stdout=lsof_80, stderr="")
        else:
            return MagicMock(returncode=1, stdout="", stderr="")
            
    with patch("subprocess.run", side_effect=fake_run) as mock_run:
        res = provider.capture(context)
        
    port_art = next(a for a in res.artifacts if a.name == "ports.txt")
    assert port_art.status == "SUCCESS"
    assert "Port 80 Listening" in port_art.content
    assert "Port: 443" in port_art.content
    assert "Listening: false" in port_art.content
    
    print("PASSED")

# Test 5: nginx -t Validation
def test_nginx_test_validation():
    print("5. nginx -t Configuration Validation ... ", end="", flush=True)
    provider = MacOSNginxSnapshotProvider()
    context = SnapshotContext(
        incident_id="INC-NG-TEST",
        target_name="Target",
        config={
            "snapshot": {
                "providers": {
                    "nginx": {
                        "service": {
                            "nginx_binary": "/usr/sbin/nginx",
                            "nginx_config": "/etc/nginx/nginx.conf"
                        }
                    }
                }
            }
        },
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    
    # 1. Config Test Success
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="nginx: configuration file /etc/nginx/nginx.conf test is successful")
        res = provider.capture(context)
        
    test_art = next(a for a in res.artifacts if a.name == "config_test.txt")
    assert test_art.status == "SUCCESS"
    assert "test is successful" in test_art.content
    # Verify shell=False was used
    mock_run.assert_any_call(["/usr/sbin/nginx", "-t", "-c", "/etc/nginx/nginx.conf"], capture_output=True, text=True, shell=False, timeout=2.0)
    
    # 2. Config Test Failure
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="nginx: [emerg] invalid parameter")
        res = provider.capture(context)
        
    test_art = next(a for a in res.artifacts if a.name == "config_test.txt")
    assert test_art.status == "SUCCESS" # The check itself succeeded in running and returning data
    assert test_art.exit_code == 1
    assert "invalid parameter" in test_art.content
    
    print("PASSED")

# Test 6: Failure Semantics
def test_failure_semantics():
    print("6. Failure & Timeout Semantics ........ ", end="", flush=True)
    provider = MacOSNginxSnapshotProvider()
    context = SnapshotContext(
        incident_id="INC-NG-SEM",
        target_name="Target",
        config={},
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    
    # Mixed success/fail -> PARTIAL
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(returncode=1, stdout="", stderr="config error"), # config_test.txt
            MagicMock(returncode=0, stdout="PID COMMAND", stderr=""),   # processes.txt
            MagicMock(returncode=0, stdout="lsof output", stderr="")    # ports.txt
        ]
        res = provider.capture(context)
        assert res.status == "PARTIAL"
        
    # All fail -> FAILED
    with patch("subprocess.run", side_effect=OSError("binary missing")):
        res = provider.capture(context)
        assert res.status == "FAILED"
        
    print("PASSED")

# Test 7: Storage Structure
def test_storage_structure():
    print("7. Storage Structure & Files .......... ", end="", flush=True)
    SnapshotEngine._providers = []
    p = MacOSNginxSnapshotProvider()
    SnapshotEngine.register_provider(p)
    
    incident_id = "INC-NG-STOR"
    setup_clean_evidence_dir(incident_id)
    
    config = {
        "snapshot": {
            "providers": {
                "nginx": {
                    "enabled": True,
                    "logs": {
                        "access_log_path": "temp_access.log",
                        "error_log_path": "temp_error.log"
                    }
                }
            }
        }
    }
    
    with open("temp_access.log", "w") as f:
        f.write("access line\n")
    with open("temp_error.log", "w") as f:
        f.write("error line\n")
        
    try:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="output", stderr="")
            SnapshotEngine.run(incident_id, "Target", config)
            
        evidence_dir = os.path.join("incidents", incident_id, "evidence")
        nginx_dir = os.path.join(evidence_dir, "nginx")
        
        # Verify physical file existence
        assert os.path.isfile(os.path.join(evidence_dir, "manifest.json"))
        assert os.path.isfile(os.path.join(nginx_dir, "access.log"))
        assert os.path.isfile(os.path.join(nginx_dir, "error.log"))
        assert os.path.isfile(os.path.join(nginx_dir, "processes.txt"))
        assert os.path.isfile(os.path.join(nginx_dir, "ports.txt"))
        assert os.path.isfile(os.path.join(nginx_dir, "config_test.txt"))
        assert os.path.isfile(os.path.join(nginx_dir, "metadata.json"))
        
    finally:
        cleanup_evidence_dir(incident_id)
        for log in ["temp_access.log", "temp_error.log"]:
            if os.path.exists(log):
                os.remove(log)
                
    print("PASSED")

# Test 8: Configuration Fallbacks
def test_configuration_fallbacks():
    print("8. Configuration Fallbacks Resolution .. ", end="", flush=True)
    provider = MacOSNginxSnapshotProvider()
    
    # 1. Fallback to collectors.nginx when snapshot.providers.nginx paths are omitted
    context = SnapshotContext(
        incident_id="INC-NG-CONF",
        target_name="Target",
        config={
            "collectors": {
                "nginx": {
                    "binary_path": "/opt/homebrew/bin/nginx",
                    "config_path": "/opt/homebrew/etc/nginx/nginx.conf",
                    "access_log_path": "fallback_access.log",
                    "error_log_path": "fallback_error.log"
                }
            },
            "snapshot": {
                "providers": {
                    "nginx": {
                        "enabled": True
                    }
                }
            }
        },
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    
    # Check that it uses fallback logs if we run it (will fail to find fallback_access.log but we assert it tries to read fallback_access.log)
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        res = provider.capture(context)
        
    access_art = next(a for a in res.artifacts if a.name == "access.log")
    # Tries to find "fallback_access.log" and errors with File not found since it doesn't exist
    assert "fallback_access.log" in access_art.error_message
    
    print("PASSED")

# Test 9: Observer-Only Safety Audit
def test_observer_only_safety():
    print("9. Observer-Only Safety Audit ........ ", end="", flush=True)
    nginx_file = "app/snapshot/providers/nginx.py"
    mutating_terms = ["kill", "terminate", "reload", "stop", "restart", "os.system"]
    
    with open(nginx_file, "r") as f:
        content = f.read()
        
    for term in mutating_terms:
        # Check comment safety rules
        lines = content.splitlines()
        for idx, line in enumerate(lines):
            if term in line:
                trimmed = line.strip()
                assert trimmed.startswith("#"), f"Mutating/restricted term '{term}' found in non-comment line {idx+1}: {line}"
                
    print("PASSED")

def main():
    print("==================================================")
    print("Starting Type 1 Verification (Milestone 9 - Batch 3)")
    print("==================================================")
    try:
        test_log_evidence()
        test_redaction()
        test_process_evidence()
        test_port_evidence()
        test_nginx_test_validation()
        test_failure_semantics()
        test_storage_structure()
        test_configuration_fallbacks()
        test_observer_only_safety()
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
