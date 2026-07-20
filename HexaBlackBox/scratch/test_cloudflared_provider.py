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

from app.snapshot.models import SnapshotContext, CapturedArtifact, ProviderCaptureResult
from app.snapshot.engine import SnapshotEngine
from app.snapshot.providers.cloudflared import MacOSCloudflaredSnapshotProvider, _token_match_process

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
    provider = MacOSCloudflaredSnapshotProvider()
    
    # Mock ps command output
    ps_stdout = (
        "  PID  PPID  %CPU  %MEM COMMAND\n"
        " 1000   100   0.1   0.2 /usr/local/bin/cloudflared tunnel run mac-mini\n"
        " 1001   100   0.0   0.1 /opt/notacloudflared/helper --args\n"
        " 1002   100   0.0   0.1 /usr/local/bin/cloudflared-helper\n"
        " 1003   100   0.0   0.1 cloudflared\n"
    )
    
    context = SnapshotContext(
        incident_id="INC-CF-PROC",
        target_name="Target",
        config={
            "snapshot": {
                "providers": {
                    "cloudflared": {
                        "process_signature": ["cloudflared"]
                    }
                }
            }
        },
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    
    # 1. Real cloudflared matches, notacloudflared/cloudflared-helper doesn't
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=ps_stdout, stderr="")
        res = provider.capture(context)
        
    proc_art = next(a for a in res.artifacts if a.name == "cloudflared_processes.txt")
    assert proc_art.status == "SUCCESS"
    assert "1000" in proc_art.content  # Matches because basename is cloudflared
    assert "1003" in proc_art.content  # Matches exact token
    assert "1001" not in proc_art.content  # notacloudflared skipped
    assert "1002" not in proc_art.content  # cloudflared-helper skipped
    
    # 2. Process absent
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="  PID  PPID  %CPU  %MEM COMMAND\n", stderr="")
        res = provider.capture(context)
    proc_art = next(a for a in res.artifacts if a.name == "cloudflared_processes.txt")
    assert proc_art.status == "SUCCESS"
    assert "cloudflared: No matching processes found at snapshot time." in proc_art.content
    
    # 3. Process check timeout
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["ps"], 1.0)):
        res = provider.capture(context)
    proc_art = next(a for a in res.artifacts if a.name == "cloudflared_processes.txt")
    assert proc_art.status == "TIMEOUT"
    
    # 4. Process check failure
    with patch("subprocess.run", side_effect=Exception("OS error")):
        res = provider.capture(context)
    proc_art = next(a for a in res.artifacts if a.name == "cloudflared_processes.txt")
    assert proc_art.status == "FAILED"
    
    print("PASSED")

# Test 2: Log Capture
def test_logs():
    print("2. Log Capture Verification ............ ", end="", flush=True)
    provider = MacOSCloudflaredSnapshotProvider()
    
    context = SnapshotContext(
        incident_id="INC-CF-LOG",
        target_name="Target",
        config={
            "snapshot": {
                "providers": {
                    "cloudflared": {
                        "log_path": "dummy.log",
                        "max_lines": 5,
                        "max_bytes": 100
                    }
                }
            }
        },
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    
    # 1. Normal log tail with secret redaction
    dummy_log_content = (
        "line 1: connecting...\n"
        "line 2: Authorization: Bearer secret_jwt_payload_here\n"
        "line 3: session established\n"
    )
    
    # Mock _tail_file
    with patch("app.snapshot.providers.cloudflared._tail_file", return_value=(dummy_log_content, False, 3, len(dummy_log_content))):
        res = provider.capture(context)
        
    log_art = next(a for a in res.artifacts if a.name == "cloudflared.log")
    assert log_art.status == "SUCCESS"
    assert "secret_jwt_payload_here" not in log_art.content
    assert "<REDACTED_TOKEN>" in log_art.content or "<REDACTED>" in log_art.content
    
    # 2. Empty log
    with patch("app.snapshot.providers.cloudflared._tail_file", return_value=("", False, 0, 0)):
        with patch("os.path.exists", return_value=True):
            res = provider.capture(context)
    log_art = next(a for a in res.artifacts if a.name == "cloudflared.log")
    assert log_art.status == "SUCCESS"
    assert "Log file existed but was empty at snapshot time." in log_art.content
    
    # 3. Missing log (FileNotFoundError)
    with patch("app.snapshot.providers.cloudflared._tail_file", side_effect=FileNotFoundError("Log missing")):
        res = provider.capture(context)
    log_art = next(a for a in res.artifacts if a.name == "cloudflared.log")
    assert log_art.status == "FAILED"
    
    # 4. Unreadable log (PermissionError)
    with patch("app.snapshot.providers.cloudflared._tail_file", side_effect=PermissionError("Log unreadable")):
        res = provider.capture(context)
    log_art = next(a for a in res.artifacts if a.name == "cloudflared.log")
    assert log_art.status == "FAILED"
    
    print("PASSED")

# Test 3: Tunnel Status
def test_tunnel_status():
    print("3. Tunnel Status Verification .......... ", end="", flush=True)
    provider = MacOSCloudflaredSnapshotProvider()
    
    context = SnapshotContext(
        incident_id="INC-CF-STATUS",
        target_name="Target",
        config={
            "snapshot": {
                "providers": {
                    "cloudflared": {
                        "tunnel_name": "mac-mini",
                        "status_timeout": 2.0
                    }
                }
            }
        },
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    
    # 1. Successful status info
    status_stdout = "Tunnel ID: 123-abc\nConnections: 4 active\n"
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=status_stdout, stderr="")
        res = provider.capture(context)
    ts_art = next(a for a in res.artifacts if a.name == "tunnel_status.txt")
    assert ts_art.status == "SUCCESS"
    assert "Tunnel ID: 123-abc" in ts_art.content
    
    # 2. Non-zero exit code (credentials missing/offline) -> treated as SUCCESS (forensic observation)
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Failed to authenticate credentials")
        res = provider.capture(context)
    ts_art = next(a for a in res.artifacts if a.name == "tunnel_status.txt")
    assert ts_art.status == "SUCCESS"
    assert "Failed to authenticate credentials" in ts_art.content
    
    # 3. Binary unavailable (FileNotFoundError) -> SUCCESS with skipped message
    with patch("subprocess.run", side_effect=FileNotFoundError()):
        res = provider.capture(context)
    ts_art = next(a for a in res.artifacts if a.name == "tunnel_status.txt")
    assert ts_art.status == "SUCCESS"
    assert "cloudflared binary not found in PATH" in ts_art.content
    
    # 4. Command timeout -> TIMEOUT
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["cloudflared"], 2.0)):
        res = provider.capture(context)
    ts_art = next(a for a in res.artifacts if a.name == "tunnel_status.txt")
    assert ts_art.status == "TIMEOUT"
    
    # 5. Missing tunnel name -> SUCCESS with skipped message
    context_no_name = SnapshotContext(
        incident_id="INC-CF-STATUS",
        target_name="Target",
        config={"snapshot": {"providers": {"cloudflared": {"tunnel_name": ""}}}},
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    res = provider.capture(context_no_name)
    ts_art = next(a for a in res.artifacts if a.name == "tunnel_status.txt")
    assert ts_art.status == "SUCCESS"
    assert "Tunnel name not configured" in ts_art.content
    
    print("PASSED")

# Test 4: DNS Evidence
def test_dns_evidence():
    print("4. DNS Evidence Verification ........... ", end="", flush=True)
    provider = MacOSCloudflaredSnapshotProvider()
    
    context = SnapshotContext(
        incident_id="INC-CF-DNS",
        target_name="Target",
        config={
            "snapshot": {
                "providers": {
                    "cloudflared": {
                        "public_hostnames": ["healthy.com", "nxdomain.com", "timeout.com"]
                    }
                }
            }
        },
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    
    # Mock DNS resolution outputs
    def fake_run(args, **kwargs):
        cmd = " ".join(args)
        if "healthy.com" in cmd:
            return MagicMock(returncode=0, stdout="healthy.com has address 1.2.3.4", stderr="")
        elif "nxdomain.com" in cmd:
            return MagicMock(returncode=1, stdout="", stderr="Host nxdomain.com not found: 3(NXDOMAIN)")
        elif "timeout.com" in cmd:
            raise subprocess.TimeoutExpired(args, 3.0)
        else:
            raise Exception("Tool error")
            
    with patch("subprocess.run", side_effect=fake_run):
        res = provider.capture(context)
        
    dns_art = next(a for a in res.artifacts if a.name == "dns_resolution.txt")
    # Mixed results with at least one success -> SUCCESS
    assert dns_art.status == "SUCCESS"
    assert "healthy.com has address 1.2.3.4" in dns_art.content
    assert "NXDOMAIN" in dns_art.content
    assert "TIMEOUT" in dns_art.content
    
    # All NXDOMAIN -> status is still SUCCESS (forensic observation)
    context_nx = SnapshotContext(
        incident_id="INC-CF-DNS",
        target_name="Target",
        config={"snapshot": {"providers": {"cloudflared": {"public_hostnames": ["nxdomain.com"]}}}},
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    with patch("subprocess.run", side_effect=fake_run):
        res = provider.capture(context_nx)
    dns_art = next(a for a in res.artifacts if a.name == "dns_resolution.txt")
    assert dns_art.status == "SUCCESS"
    assert "NXDOMAIN" in dns_art.content
    
    # DNS tool unavailable (e.g. host and nslookup both FileNotFoundError)
    with patch("subprocess.run", side_effect=FileNotFoundError()):
        res = provider.capture(context)
    dns_art = next(a for a in res.artifacts if a.name == "dns_resolution.txt")
    assert dns_art.status == "FAILED"
    assert "DNS tool not available" in dns_art.content
    
    # No hostnames configured -> SUCCESS (skipped)
    context_none = SnapshotContext(
        incident_id="INC-CF-DNS",
        target_name="Target",
        config={"snapshot": {"providers": {"cloudflared": {"public_hostnames": []}}}},
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    res = provider.capture(context_none)
    dns_art = next(a for a in res.artifacts if a.name == "dns_resolution.txt")
    assert dns_art.status == "SUCCESS"
    assert "DNS resolution skipped" in dns_art.content
    
    print("PASSED")

# Test 5: Local Origin
def test_local_origin():
    print("5. Local Origin Verification ........... ", end="", flush=True)
    provider = MacOSCloudflaredSnapshotProvider()
    
    context = SnapshotContext(
        incident_id="INC-CF-ORIGIN",
        target_name="Target",
        config={
            "snapshot": {
                "providers": {
                    "cloudflared": {
                        "local_origin_url": "http://127.0.0.1:8002/api/health",
                        "status_timeout": 1.0
                    }
                }
            }
        },
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    
    # 1. HTTP 200 -> Reachable: true
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__.return_value = mock_resp
    with patch("urllib.request.urlopen", return_value=mock_resp):
        res = provider.capture(context)
    lo_art = next(a for a in res.artifacts if a.name == "local_origin.txt")
    assert lo_art.status == "SUCCESS"
    assert "Reachable: true" in lo_art.content
    assert "HTTP Status: 200" in lo_art.content
    
    # 2. HTTP 502 -> Reachable: false
    from urllib.error import HTTPError
    mock_err = HTTPError("http://127.0.0.1:8002", 502, "Bad Gateway", {}, None)
    with patch("urllib.request.urlopen", side_effect=mock_err):
        res = provider.capture(context)
    lo_art = next(a for a in res.artifacts if a.name == "local_origin.txt")
    assert lo_art.status == "SUCCESS"
    assert "Reachable: false" in lo_art.content
    assert "HTTP Status: 502" in lo_art.content
    
    # 3. Connection refused
    from urllib.error import URLError
    mock_url_err = URLError("Connection refused")
    with patch("urllib.request.urlopen", side_effect=mock_url_err):
        res = provider.capture(context)
    lo_art = next(a for a in res.artifacts if a.name == "local_origin.txt")
    assert lo_art.status == "SUCCESS"
    assert "Reachable: false" in lo_art.content
    assert "Connection refused" in lo_art.content
    
    # 4. Timeout
    import socket
    with patch("urllib.request.urlopen", side_effect=socket.timeout()):
        res = provider.capture(context)
    lo_art = next(a for a in res.artifacts if a.name == "local_origin.txt")
    assert lo_art.status == "TIMEOUT"
    
    print("PASSED")

# Test 6: Metrics
def test_metrics():
    print("6. Bounded Metrics Verification ........ ", end="", flush=True)
    provider = MacOSCloudflaredSnapshotProvider()
    
    context = SnapshotContext(
        incident_id="INC-CF-METRICS",
        target_name="Target",
        config={
            "snapshot": {
                "providers": {
                    "cloudflared": {
                        "metrics_url": "http://localhost:2000/metrics",
                        "status_timeout": 1.0
                    }
                }
            }
        },
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    
    metrics_data = (
        "# HELP cloudflared_tunnel_active_streams Active streams\n"
        "# TYPE cloudflared_tunnel_active_streams gauge\n"
        "cloudflared_tunnel_active_streams 5\n"
        "# HELP process_open_fds Open FDs\n"
        "# TYPE process_open_fds gauge\n"
        "process_open_fds 23\n"
        "# HELP some_unrelated_metric Unrelated\n"
        "# TYPE some_unrelated_metric counter\n"
        "some_unrelated_metric 999\n"
    )
    
    # 1. Normal metrics parsing (only allowed metrics)
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.read.return_value = metrics_data.encode("utf-8")
    with patch("urllib.request.urlopen", return_value=mock_resp):
        res = provider.capture(context)
        
    met_art = next(a for a in res.artifacts if a.name == "metrics.txt")
    assert met_art.status == "SUCCESS"
    assert "cloudflared_tunnel_active_streams" in met_art.content
    assert "process_open_fds" in met_art.content
    assert "some_unrelated_metric" not in met_art.content
    
    # 2. Metrics not configured -> SUCCESS (skipped)
    context_no_met = SnapshotContext(
        incident_id="INC-CF-METRICS",
        target_name="Target",
        config={"snapshot": {"providers": {"cloudflared": {"metrics_url": ""}}}},
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    res = provider.capture(context_no_met)
    met_art = next(a for a in res.artifacts if a.name == "metrics.txt")
    assert met_art.status == "SUCCESS"
    assert "Metrics endpoint not configured" in met_art.content
    
    print("PASSED")

# Test 7: Static Code Audit
def test_static_code_audit():
    print("7. Observer-Only & Safety Audit ........ ", end="", flush=True)
    
    # Read cloudflared provider code
    provider_file = os.path.abspath(os.path.join(os.path.dirname(__file__), "../app/snapshot/providers/cloudflared.py"))
    with open(provider_file, "r", encoding="utf-8") as f:
        code = f.read()
        
    # Ensure no forbidden mutation commands
    forbidden_terms = [
        "launchctl load", "launchctl unload", "launchctl stop", "launchctl start",
        "kill -9", "pkill", "killall", "delete-route", "add-route", "dns-set",
        "modify", "ingress-rule-add", "ingress-rule-delete"
    ]
    for term in forbidden_terms:
        assert term not in code, f"Forbidden mutation pattern found: {term}"
        
    # Ensure all subprocess calls are shell=False
    assert "shell=True" not in code, "Found shell=True call"
    
    print("PASSED")

# Test 8: Configuration fallback
def test_config_fallback():
    print("8. Configuration Fallbacks ............. ", end="", flush=True)
    provider = MacOSCloudflaredSnapshotProvider()
    
    # Fallback to collectors.cloudflared if snapshot config is empty
    context = SnapshotContext(
        incident_id="INC-CF-CFG",
        target_name="Target",
        config={
            "collectors": {
                "cloudflared": {
                    "tunnel_name": "mini-fallback",
                    "log_path": "fallback.log",
                    "log_lines": 123
                }
            }
        },
        evidence_dir="temp_dir",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock()
    )
    
    with patch("app.snapshot.providers.cloudflared._tail_file", return_value=("", False, 0, 0)) as mock_tail:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="Tunnel Info", stderr="")
            provider.capture(context)
            
            # Verify correct parameters were extracted
            mock_tail.assert_called_with("fallback.log", 123, 1048576)
            mock_run.assert_any_call(["cloudflared", "tunnel", "info", "mini-fallback"], capture_output=True, text=True, shell=False, timeout=5.0)
            
    print("PASSED")

# Test 9: End to End with SnapshotEngine
def test_engine_integration():
    print("9. Engine Integration & Storage ........ ", end="", flush=True)
    
    # Register provider
    provider = MacOSCloudflaredSnapshotProvider()
    SnapshotEngine.register_provider(provider)
    
    incident_id = "INC-CF-E2E"
    setup_clean_evidence_dir(incident_id)
    
    config = {
        "collectors": {
            "cloudflared": {
                "tunnel_name": "mac-mini",
                "log_path": "scratch/cf_test.log",
                "log_lines": 50
            }
        },
        "snapshot": {
            "providers": {
                "cloudflared": {
                    "enabled": True,
                    "public_hostnames": ["localhost"],
                    "local_origin_url": "http://127.0.0.1:8002/api/health"
                }
            }
        }
    }
    
    # Create a dummy log file
    log_file_path = "scratch/cf_test.log"
    with open(log_file_path, "w", encoding="utf-8") as f:
        f.write("Line 1: started tunnel\nLine 2: Authorization: Bearer jwt_secret_string\n")
        
    try:
        # Mock commands inside the engine execution
        ps_out = "  PID  PPID  %CPU  %MEM COMMAND\n 2000   100   0.0   0.0 cloudflared\n"
        status_out = "Tunnel ID: abc-123\n"
        dns_out = "host localhost\nlocalhost has address 127.0.0.1"
        
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        
        def fake_run(args, **kwargs):
            cmd = " ".join(args)
            if "ps" in cmd:
                return MagicMock(returncode=0, stdout=ps_out, stderr="")
            elif "info" in cmd:
                return MagicMock(returncode=0, stdout=status_out, stderr="")
            elif "host" in cmd:
                return MagicMock(returncode=0, stdout=dns_out, stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")
            
        with patch("subprocess.run", side_effect=fake_run):
            with patch("urllib.request.urlopen", return_value=mock_resp):
                manifest = SnapshotEngine.run(incident_id, "HexaBeta Backend API", config)
                
        # 1. Verify files exist on disk
        prov_dir = f"incidents/{incident_id}/evidence/cloudflared"
        assert os.path.exists(prov_dir)
        assert os.path.exists(os.path.join(prov_dir, "cloudflared_processes.txt"))
        assert os.path.exists(os.path.join(prov_dir, "tunnel_status.txt"))
        assert os.path.exists(os.path.join(prov_dir, "cloudflared.log"))
        assert os.path.exists(os.path.join(prov_dir, "dns_resolution.txt"))
        assert os.path.exists(os.path.join(prov_dir, "local_origin.txt"))
        assert os.path.exists(os.path.join(prov_dir, "metadata.json"))
        
        # 2. Verify credentials/tokens are redacted and never reach disk
        with open(os.path.join(prov_dir, "cloudflared.log"), "r") as f:
            log_content = f.read()
            assert "jwt_secret_string" not in log_content
            assert "<REDACTED_TOKEN>" in log_content or "<REDACTED>" in log_content
            
        # 3. Verify manifest
        assert manifest["incident_id"] == incident_id
        cf_res = next(r for r in manifest["results"] if r["provider_name"] == "cloudflared")
        assert cf_res["status"] == "SUCCESS"
        
    finally:
        if os.path.exists(log_file_path):
            os.remove(log_file_path)
        cleanup_evidence_dir(incident_id)
        
    print("PASSED")

def main():
    print("==================================================")
    print("Starting Type 1 Verification (Milestone 9 - Batch 5)")
    print("==================================================")
    
    try:
        test_processes()
        test_logs()
        test_tunnel_status()
        test_dns_evidence()
        test_local_origin()
        test_metrics()
        test_static_code_audit()
        test_config_fallback()
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
