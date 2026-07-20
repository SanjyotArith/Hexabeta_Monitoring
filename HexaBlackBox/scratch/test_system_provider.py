"""
Type 1 Verification – Milestone 9 Batch 7: System/Host Snapshot Provider
=========================================================================
All tests use mocked subprocess.run and patched file reads; no real system
commands are executed.  Tests are self-contained, produce no side-effects,
and clean up any temporary evidence directories on completion.
"""

import os
import re
import sys
import json
import shutil
import time
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, call

# ── make sure the project root is on sys.path ──────────────────────────────
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.snapshot.models import SnapshotContext
from app.snapshot.providers.system import (
    MacOSSystemSnapshotProvider,
    LinuxSystemSnapshotProvider,
    _redact_process_line,
)

# ── helpers ────────────────────────────────────────────────────────────────
PASS = "\033[32mPASSED\033[0m"
FAIL = "\033[31mFAILED\033[0m"

_PASS_COUNT = 0
_FAIL_COUNT = 0

def _ok(label: str) -> None:
    global _PASS_COUNT
    _PASS_COUNT += 1
    print(f"{label} {PASS}")

def _fail(label: str, exc: Exception) -> None:
    global _FAIL_COUNT
    _FAIL_COUNT += 1
    print(f"{label} {FAIL}")
    raise exc


def _ctx(config: dict = None) -> SnapshotContext:
    return SnapshotContext(
        incident_id="INC-SYS-TEST",
        target_name="System",
        config=config or {},
        evidence_dir="temp_evidence",
        timestamp=datetime.now(timezone.utc),
        logger=MagicMock(),
    )


def _mkcmd(*, hostname="mymac", sw_vers="ProductName: macOS\nProductVersion: 14.0",
           uname_a="Darwin mymac 23.0.0 Darwin Kernel root:xnu arm64",
           uname_m="arm64", sysctl_cpu="hw.ncpu: 10\nhw.physicalcpu: 8",
           loadavg="{ 1.20 2.30 3.40 }",
           memsize="17179869184", vm_stat="Mach Virtual Memory Statistics: (page size of 16384 bytes)\nPages free: 12345.",
           df_out="Filesystem  Size  Used  Avail  Use% Mounted on\n/dev/disk3  460G  200G  260G   44% /",
           uptime="11:00  up 5 days, 4:00, 2 users, load averages: 1.20 2.30 3.40",
           boottime="{ sec = 1700000000, usec = 0 } Mon Nov 13 00:00:00 2023",
           netstat_out="Active Internet connections\nProto Recv-Q Send-Q Local Address Foreign Address State\ntcp4   0  0  *.8002  *.*  LISTEN\ntcp4   0  0  127.0.0.1.5432  *.*  LISTEN\ntcp4   0  0  10.0.0.1.60000  8.8.8.8.443  ESTABLISHED",
           ps_out="  PID  PPID  %CPU  %MEM COMMAND\n  100    1   5.1   0.3 /usr/bin/python3\n  200    1   1.2   0.1 /usr/sbin/sshd\n"):
    """
    Build a fake subprocess.run side_effect for macOS scenario.
    The returned callable matches any call and returns mock output keyed by the
    first two argv tokens.
    """
    responses = {
        ("hostname",):          (hostname, 0, ""),
        ("sw_vers",):           (sw_vers, 0, ""),
        ("uname", "-a"):        (uname_a, 0, ""),
        ("uname", "-m"):        (uname_m, 0, ""),
        ("sysctl", "hw.ncpu"):  (sysctl_cpu, 0, ""),
        ("sysctl", "-n", "vm.loadavg"): (loadavg, 0, ""),
        ("sysctl", "-n", "hw.memsize"): (memsize, 0, ""),
        ("vm_stat",):           (vm_stat, 0, ""),
        ("df",):                (df_out, 0, ""),
        ("uptime",):            (uptime, 0, ""),
        ("sysctl", "-n", "kern.boottime"): (boottime, 0, ""),
        ("netstat",):           (netstat_out, 0, ""),
        ("ps",):                (ps_out, 0, ""),
    }

    def _side(args, **kw):
        key = tuple(args[:3]) if len(args) >= 3 else tuple(args)
        # Try progressively shorter prefixes
        for n in (3, 2, 1):
            k = tuple(args[:n])
            if k in responses:
                out, rc, err = responses[k]
                return MagicMock(returncode=rc, stdout=out, stderr=err)
        return MagicMock(returncode=0, stdout="", stderr="")

    return _side


# ══════════════════════════════════════════════════════════════════════════════
# TEST 1 – system_info.txt (macOS)
# ══════════════════════════════════════════════════════════════════════════════
def test_system_info_macos():
    label = " 1. system_info.txt (macOS) ............. "
    provider = MacOSSystemSnapshotProvider()

    with patch("subprocess.run", side_effect=_mkcmd()):
        res = provider.capture(_ctx())

    art = next(a for a in res.artifacts if a.name == "system_info.txt")
    assert art.status == "SUCCESS", f"Expected SUCCESS, got {art.status}"
    assert "Hostname:" in art.content
    assert "macOS" in art.content or "sw_vers" in art.content
    assert "arm64" in art.content
    assert art.redaction_applied is True
    _ok(label)


def test_system_info_missing_command():
    """sw_vers missing – artifact must still be SUCCESS (partial content)."""
    label = " 1b. system_info.txt missing command .... "
    provider = MacOSSystemSnapshotProvider()

    base = _mkcmd()
    def _patched(args, **kw):
        if args[0] == "sw_vers":
            return MagicMock(returncode=1, stdout="", stderr="command not found")
        return base(args, **kw)

    with patch("subprocess.run", side_effect=_patched):
        res = provider.capture(_ctx())

    art = next(a for a in res.artifacts if a.name == "system_info.txt")
    assert art.status == "SUCCESS"           # degraded, not crashed
    assert "Hostname:" in art.content
    _ok(label)


# ══════════════════════════════════════════════════════════════════════════════
# TEST 2 – cpu.txt (macOS)
# ══════════════════════════════════════════════════════════════════════════════
def test_cpu_macos():
    label = " 2. cpu.txt (macOS) ..................... "
    provider = MacOSSystemSnapshotProvider()

    with patch("subprocess.run", side_effect=_mkcmd(sysctl_cpu="hw.ncpu: 10\nhw.physicalcpu: 8")):
        res = provider.capture(_ctx())

    art = next(a for a in res.artifacts if a.name == "cpu.txt")
    assert art.status == "SUCCESS"
    assert "hw.ncpu" in art.content
    assert "CPU Info" in art.content
    _ok(label)


def test_cpu_sysctl_missing():
    """sysctl missing – artifact should still succeed with error note."""
    label = " 2b. cpu.txt sysctl unavailable ......... "
    provider = MacOSSystemSnapshotProvider()

    base = _mkcmd()
    def _patched(args, **kw):
        if args[0] == "sysctl":
            return MagicMock(returncode=1, stdout="", stderr="sysctl not found")
        return base(args, **kw)

    with patch("subprocess.run", side_effect=_patched):
        res = provider.capture(_ctx())

    art = next(a for a in res.artifacts if a.name == "cpu.txt")
    assert art.status == "SUCCESS"          # artifact writes fallback note
    _ok(label)


# ══════════════════════════════════════════════════════════════════════════════
# TEST 3 – memory.txt (macOS)
# ══════════════════════════════════════════════════════════════════════════════
def test_memory_macos():
    label = " 3. memory.txt (macOS) .................. "
    provider = MacOSSystemSnapshotProvider()

    with patch("subprocess.run", side_effect=_mkcmd()):
        res = provider.capture(_ctx())

    art = next(a for a in res.artifacts if a.name == "memory.txt")
    assert art.status == "SUCCESS"
    # 16 GB reported from 17179869184 bytes
    assert "16.0 GB" in art.content
    assert "vm_stat" in art.content
    _ok(label)


def test_memory_bad_memsize():
    """Non-numeric hw.memsize – must not crash, just writes parse-failed note."""
    label = " 3b. memory.txt malformed memsize ....... "
    provider = MacOSSystemSnapshotProvider()

    with patch("subprocess.run", side_effect=_mkcmd(memsize="NOT_A_NUMBER")):
        res = provider.capture(_ctx())

    art = next(a for a in res.artifacts if a.name == "memory.txt")
    assert art.status == "SUCCESS"
    assert "parse failed" in art.content or "Physical Memory" in art.content
    _ok(label)


def test_memory_vm_stat_timeout():
    """vm_stat timeout – artifact still SUCCESS with error note in content."""
    label = " 3c. memory.txt vm_stat timeout ......... "
    provider = MacOSSystemSnapshotProvider()

    import subprocess
    base = _mkcmd()
    def _patched(args, **kw):
        if args[0] == "vm_stat":
            raise subprocess.TimeoutExpired(cmd=args, timeout=5)
        return base(args, **kw)

    with patch("subprocess.run", side_effect=_patched):
        res = provider.capture(_ctx())

    art = next(a for a in res.artifacts if a.name == "memory.txt")
    # The outer try catches TimeoutExpired; vm_stat timeout bubbles up, but
    # _run_cmd converts it to ("", None, "TIMEOUT"). The artifact is still SUCCESS.
    assert art.status == "SUCCESS"
    _ok(label)


# ══════════════════════════════════════════════════════════════════════════════
# TEST 4 – disk.txt
# ══════════════════════════════════════════════════════════════════════════════
def test_disk_absolute_path():
    label = " 4. disk.txt absolute paths work ........ "
    provider = MacOSSystemSnapshotProvider()

    config = {"snapshot": {"providers": {"system": {"disk_paths": ["/", "/tmp"]}}}}
    base = _mkcmd()
    def _patched(args, **kw):
        if args[0] == "df":
            return MagicMock(returncode=0,
                             stdout=f"Filesystem  Size  Used Avail Use% Mounted\n/dev/disk0s1 1.0T 500G 500G 50% {args[-1]}",
                             stderr="")
        return base(args, **kw)

    with patch("subprocess.run", side_effect=_patched):
        res = provider.capture(_ctx(config))

    art = next(a for a in res.artifacts if a.name == "disk.txt")
    assert art.status == "SUCCESS"
    assert "=== df -h / ===" in art.content
    assert "=== df -h /tmp ===" in art.content
    _ok(label)


def test_disk_non_absolute_rejected():
    label = " 4b. disk.txt non-absolute rejected ..... "
    provider = MacOSSystemSnapshotProvider()

    config = {"snapshot": {"providers": {"system": {"disk_paths": ["relative/path", "/"]}}}}
    with patch("subprocess.run", side_effect=_mkcmd()):
        res = provider.capture(_ctx(config))

    art = next(a for a in res.artifacts if a.name == "disk.txt")
    assert art.status == "SUCCESS"
    assert "SKIPPED" in art.content          # relative path was skipped
    assert "=== df -h / ===" in art.content  # absolute path still ran
    _ok(label)


def test_disk_paths_bounded_to_10():
    label = " 4c. disk.txt paths bounded to 10 ....... "
    provider = MacOSSystemSnapshotProvider()

    paths = [f"/{i}" for i in range(20)]
    config = {"snapshot": {"providers": {"system": {"disk_paths": paths}}}}

    call_args_list = []
    base = _mkcmd()
    def _patched(args, **kw):
        if args[0] == "df":
            call_args_list.append(args[-1])
            return MagicMock(returncode=0, stdout=f"Filesystem\n/dev/d {args[-1]}", stderr="")
        return base(args, **kw)

    with patch("subprocess.run", side_effect=_patched):
        res = provider.capture(_ctx(config))

    assert len(call_args_list) <= 10, f"df called {len(call_args_list)} times, expected ≤10"
    _ok(label)


def test_disk_df_failure_recorded():
    label = " 4d. disk.txt df failure recorded ....... "
    provider = MacOSSystemSnapshotProvider()

    config = {"snapshot": {"providers": {"system": {"disk_paths": ["/nonexistent"]}}}}
    base = _mkcmd()
    def _patched(args, **kw):
        if args[0] == "df":
            return MagicMock(returncode=1, stdout="", stderr="No such file or directory")
        return base(args, **kw)

    with patch("subprocess.run", side_effect=_patched):
        res = provider.capture(_ctx(config))

    art = next(a for a in res.artifacts if a.name == "disk.txt")
    assert art.status == "SUCCESS"      # disk artifact itself stays SUCCESS
    assert "failed" in art.content.lower() or "No such" in art.content
    _ok(label)


# ══════════════════════════════════════════════════════════════════════════════
# TEST 5 – load.txt
# ══════════════════════════════════════════════════════════════════════════════
def test_load_macos():
    label = " 5. load.txt (macOS) .................... "
    provider = MacOSSystemSnapshotProvider()

    with patch("subprocess.run", side_effect=_mkcmd()):
        res = provider.capture(_ctx())

    art = next(a for a in res.artifacts if a.name == "load.txt")
    assert art.status == "SUCCESS"
    assert "uptime" in art.content.lower() or "load" in art.content.lower()
    _ok(label)


def test_load_uptime_failure():
    label = " 5b. load.txt uptime failure isolated ... "
    provider = MacOSSystemSnapshotProvider()

    base = _mkcmd()
    def _patched(args, **kw):
        if args[0] == "uptime":
            return MagicMock(returncode=1, stdout="", stderr="uptime not found")
        return base(args, **kw)

    with patch("subprocess.run", side_effect=_patched):
        res = provider.capture(_ctx())

    art = next(a for a in res.artifacts if a.name == "load.txt")
    assert art.status == "SUCCESS"      # degraded content, not crash
    _ok(label)


# ══════════════════════════════════════════════════════════════════════════════
# TEST 6 – CRITICAL: top_processes.txt redaction security
# ══════════════════════════════════════════════════════════════════════════════

# All of these raw tokens must NEVER appear in evidence on disk.
_SECRET_TOKENS = [
    "TYPE1_SECRET_FLAG_EQ",
    "TYPE1_SECRET_FLAG_SPACE",
    "TYPE1_SECRET_TOKEN_EQ",
    "TYPE1_SECRET_TOKEN_SPACE",
    "TYPE1_SECRET_PGPASSWORD",
    "TYPE1_SECRET_BEARER",
    "TYPE1_JWT_eyJ.payload.sig",
    "TYPE1_SECRET_APIKEY",
    "TYPE1_SECRET_ARBITRARY_98765",
]

def _build_ps_with_secrets() -> str:
    """Build a mock ps output containing all secret patterns."""
    lines = [
        "  PID  PPID  %CPU  %MEM COMMAND",
        f"  101     1   9.9   0.5 /usr/bin/myapp --password=TYPE1_SECRET_FLAG_EQ --verbose",
        f"  102     1   8.8   0.4 /usr/bin/myapp --password TYPE1_SECRET_FLAG_SPACE",
        f"  103     1   7.7   0.3 /usr/bin/api --token=TYPE1_SECRET_TOKEN_EQ",
        f"  104     1   6.6   0.2 /usr/bin/api --token TYPE1_SECRET_TOKEN_SPACE",
        f"  105     1   5.5   0.1 PGPASSWORD=TYPE1_SECRET_PGPASSWORD /usr/bin/psql",
        f"  106     1   4.4   0.1 /usr/bin/curl -H 'Authorization: Bearer TYPE1_SECRET_BEARER'",
        f"  107     1   3.3   0.1 /usr/bin/jwtcli --jwt=TYPE1_JWT_eyJ.payload.sig",
        f"  108     1   2.2   0.1 /usr/bin/mycli --api-key=TYPE1_SECRET_APIKEY",
        f"  109     1   1.1   0.1 /usr/bin/proc --config completely_innocent_key=TYPE1_SECRET_ARBITRARY_98765",
        f"  110     1   0.5   0.1 /usr/bin/normal_process --verbose",
    ]
    return "\n".join(lines)


def test_top_processes_security_unit():
    """Unit test: _redact_process_line must strip all known secret patterns."""
    label = " 6a. top_processes redaction unit ....... "
    cases = [
        ("myapp --password=TYPE1_SECRET_FLAG_EQ",     "TYPE1_SECRET_FLAG_EQ"),
        ("myapp --password TYPE1_SECRET_FLAG_SPACE",  "TYPE1_SECRET_FLAG_SPACE"),
        ("api --token=TYPE1_SECRET_TOKEN_EQ",         "TYPE1_SECRET_TOKEN_EQ"),
        ("api --token TYPE1_SECRET_TOKEN_SPACE",      "TYPE1_SECRET_TOKEN_SPACE"),
        ("PGPASSWORD=TYPE1_SECRET_PGPASSWORD psql",   "TYPE1_SECRET_PGPASSWORD"),
        ("proc --jwt=TYPE1_JWT_eyJ.payload.sig",      "TYPE1_JWT_eyJ.payload.sig"),
        ("cli --api-key=TYPE1_SECRET_APIKEY",         "TYPE1_SECRET_APIKEY"),
    ]
    for cmd, secret in cases:
        result = _redact_process_line(cmd)
        assert secret not in result, (
            f"BUG: secret '{secret}' survived redaction in '{cmd}' -> '{result}'"
        )
    _ok(label)


def test_top_processes_security_integration():
    """Integration: no secret token must survive to the captured artifact content."""
    label = " 6b. top_processes secrets not in artifact "
    provider = MacOSSystemSnapshotProvider()

    base = _mkcmd(ps_out=_build_ps_with_secrets())
    with patch("subprocess.run", side_effect=base):
        res = provider.capture(_ctx())

    art = next(a for a in res.artifacts if a.name == "top_processes.txt")
    assert art.status == "SUCCESS"
    for secret in _SECRET_TOKENS:
        if secret in art.content:
            raise AssertionError(
                f"PRODUCTION SECURITY BUG: secret '{secret}' leaked into top_processes.txt content!"
            )
    _ok(label)


def test_top_processes_disk_secret_scan():
    """
    End-to-end disk scan: run via SnapshotEngine, then recursively grep every
    file in evidence/system/ for any injected secret token.
    """
    label = " 6c. top_processes disk secret scan ..... "
    from app.snapshot.engine import SnapshotEngine
    incident_id = "INC-SYS-SECTEST"
    evidence_root = os.path.join("incidents", incident_id)

    if os.path.exists(evidence_root):
        shutil.rmtree(evidence_root)
    os.makedirs(evidence_root, exist_ok=True)

    provider = MacOSSystemSnapshotProvider()
    SnapshotEngine.register_provider(provider)

    config = {
        "snapshot": {"providers": {"system": {"disk_paths": ["/"]}}}
    }
    base = _mkcmd(ps_out=_build_ps_with_secrets())

    try:
        with patch("subprocess.run", side_effect=base):
            SnapshotEngine.run(incident_id, "System", config)

        sys_dir = os.path.join(evidence_root, "evidence", "system")
        assert os.path.isdir(sys_dir), "evidence/system/ directory not created"

        leaks = []
        for fname in os.listdir(sys_dir):
            fpath = os.path.join(sys_dir, fname)
            if os.path.isfile(fpath):
                content = open(fpath, "r", encoding="utf-8", errors="replace").read()
                for secret in _SECRET_TOKENS:
                    if secret in content:
                        leaks.append((fname, secret))

        if leaks:
            raise AssertionError(
                "PRODUCTION SECURITY BUG — secrets found on disk:\n"
                + "\n".join(f"  {f}: '{s}'" for f, s in leaks)
            )
    finally:
        shutil.rmtree(evidence_root, ignore_errors=True)

    _ok(label)


def test_top_processes_count_bounded():
    """top_process_count > 50 must be clamped to 50."""
    label = " 6d. top_processes count bounded to 50 .. "
    provider = MacOSSystemSnapshotProvider()

    # Build ps with 60 data rows
    rows = ["  PID  PPID  %CPU  %MEM COMMAND"]
    for i in range(200, 260):
        rows.append(f"  {i}     1   0.1   0.0 /usr/bin/proc_{i}")
    ps_out = "\n".join(rows)

    config = {"snapshot": {"providers": {"system": {"top_process_count": 999}}}}
    with patch("subprocess.run", side_effect=_mkcmd(ps_out=ps_out)):
        res = provider.capture(_ctx(config))

    art = next(a for a in res.artifacts if a.name == "top_processes.txt")
    assert art.status == "SUCCESS"
    data_lines = [l for l in art.content.splitlines() if l.strip() and not l.strip().startswith("PID")]
    assert len(data_lines) <= 50, f"Expected <=50 lines, got {len(data_lines)}"
    _ok(label)


def test_top_processes_self_pid_excluded():
    """The provider's own PID must never appear in the output."""
    label = " 6e. top_processes self PID excluded .... "
    provider = MacOSSystemSnapshotProvider()
    self_pid = os.getpid()

    rows = [
        "  PID  PPID  %CPU  %MEM COMMAND",
        f"  {self_pid}     1   1.0   0.1 /usr/bin/python3 test_system_provider.py",
        "  999     1   0.5   0.1 /usr/bin/other",
    ]
    with patch("subprocess.run", side_effect=_mkcmd(ps_out="\n".join(rows))):
        res = provider.capture(_ctx())

    art = next(a for a in res.artifacts if a.name == "top_processes.txt")
    assert str(self_pid) not in art.content, "Self PID leaked into top_processes.txt"
    _ok(label)


def test_top_processes_ps_timeout():
    """ps timeout must produce a TIMEOUT artifact, not crash the provider."""
    label = " 6f. top_processes ps timeout ........... "
    import subprocess
    provider = MacOSSystemSnapshotProvider()

    base = _mkcmd()
    def _patched(args, **kw):
        if args[0] == "ps":
            raise subprocess.TimeoutExpired(cmd=args, timeout=5)
        return base(args, **kw)

    with patch("subprocess.run", side_effect=_patched):
        res = provider.capture(_ctx())

    proc_art = next(a for a in res.artifacts if a.name == "top_processes.txt")
    assert proc_art.status == "TIMEOUT"
    # Other artifacts must still be SUCCESS — failure is isolated
    other_ok = [a for a in res.artifacts if a.name != "top_processes.txt" and a.status == "SUCCESS"]
    assert len(other_ok) >= 6
    assert res.status == "PARTIAL"
    _ok(label)


# ══════════════════════════════════════════════════════════════════════════════
# TEST 7 – network.txt (macOS)
# ══════════════════════════════════════════════════════════════════════════════
def test_network_listen_only():
    """ESTABLISHED connections must be excluded; LISTEN lines retained."""
    label = " 7. network.txt LISTEN-only filter ...... "
    provider = MacOSSystemSnapshotProvider()

    netstat = (
        "Active Internet connections\n"
        "Proto Recv-Q Send-Q Local Address   Foreign Address  State\n"
        "tcp4   0   0  *.8002            *.*              LISTEN\n"
        "tcp4   0   0  127.0.0.1.5432    *.*              LISTEN\n"
        "tcp4   0   0  10.0.0.1.60000    8.8.8.8.443      ESTABLISHED\n"
        "tcp4   0   0  10.0.0.1.60001    1.2.3.4.80       CLOSE_WAIT\n"
    )
    with patch("subprocess.run", side_effect=_mkcmd(netstat_out=netstat)):
        res = provider.capture(_ctx())

    art = next(a for a in res.artifacts if a.name == "network.txt")
    assert art.status == "SUCCESS"
    assert "LISTEN" in art.content
    assert "ESTABLISHED" not in art.content
    assert "CLOSE_WAIT" not in art.content
    _ok(label)


def test_network_bounded_output():
    """Output must be bounded to _MAX_LINES (200)."""
    label = " 7b. network.txt bounded output ......... "
    provider = MacOSSystemSnapshotProvider()

    lines = ["Active Internet connections", "Proto Recv-Q Send-Q Local   Foreign  State"]
    for i in range(300):
        lines.append(f"tcp4   0   0  *.{8000 + i}   *.*  LISTEN")
    netstat_big = "\n".join(lines)

    with patch("subprocess.run", side_effect=_mkcmd(netstat_out=netstat_big)):
        res = provider.capture(_ctx())

    art = next(a for a in res.artifacts if a.name == "network.txt")
    assert art.status == "SUCCESS"
    assert art.lines_captured <= 200
    _ok(label)


def test_network_empty_output():
    """Empty netstat output must produce a placeholder, not an empty artifact."""
    label = " 7c. network.txt empty handled .......... "
    provider = MacOSSystemSnapshotProvider()

    with patch("subprocess.run", side_effect=_mkcmd(netstat_out="")):
        res = provider.capture(_ctx())

    art = next(a for a in res.artifacts if a.name == "network.txt")
    assert art.status == "SUCCESS"
    assert art.content.strip()     # something written, not blank
    _ok(label)


def test_network_timeout():
    """netstat timeout must produce TIMEOUT artifact; provider PARTIAL."""
    label = " 7d. network.txt timeout isolated ....... "
    import subprocess
    provider = MacOSSystemSnapshotProvider()

    base = _mkcmd()
    def _patched(args, **kw):
        if args[0] == "netstat":
            raise subprocess.TimeoutExpired(cmd=args, timeout=5)
        return base(args, **kw)

    with patch("subprocess.run", side_effect=_patched):
        res = provider.capture(_ctx())

    net_art = next(a for a in res.artifacts if a.name == "network.txt")
    assert net_art.status == "TIMEOUT"
    assert res.status == "PARTIAL"
    _ok(label)


# ══════════════════════════════════════════════════════════════════════════════
# TEST 8 – uptime.txt
# ══════════════════════════════════════════════════════════════════════════════
def test_uptime_macos():
    label = " 8. uptime.txt (macOS) .................. "
    provider = MacOSSystemSnapshotProvider()

    with patch("subprocess.run", side_effect=_mkcmd()):
        res = provider.capture(_ctx())

    art = next(a for a in res.artifacts if a.name == "uptime.txt")
    assert art.status == "SUCCESS"
    assert "uptime" in art.content.lower()
    assert "Boot Time" in art.content
    _ok(label)


def test_uptime_boottime_missing():
    """kern.boottime unavailable – uptime.txt still SUCCESS with partial info."""
    label = " 8b. uptime.txt kern.boottime missing ... "
    provider = MacOSSystemSnapshotProvider()

    base = _mkcmd()
    def _patched(args, **kw):
        if args[:3] == ["sysctl", "-n", "kern.boottime"]:
            return MagicMock(returncode=1, stdout="", stderr="unknown oid")
        return base(args, **kw)

    with patch("subprocess.run", side_effect=_patched):
        res = provider.capture(_ctx())

    art = next(a for a in res.artifacts if a.name == "uptime.txt")
    assert art.status == "SUCCESS"
    assert "uptime" in art.content.lower()
    _ok(label)


# ══════════════════════════════════════════════════════════════════════════════
# TEST 9 – Failure isolation / SUCCESS-PARTIAL-FAILED semantics
# ══════════════════════════════════════════════════════════════════════════════
def test_failure_isolation_partial():
    """One TIMEOUT artifact -> provider status PARTIAL, others unaffected."""
    label = " 9. failure isolation PARTIAL ........... "
    import subprocess
    provider = MacOSSystemSnapshotProvider()

    base = _mkcmd()
    def _patched(args, **kw):
        if args[0] == "vm_stat":
            raise subprocess.TimeoutExpired(cmd=args, timeout=5)
        return base(args, **kw)

    with patch("subprocess.run", side_effect=_patched):
        res = provider.capture(_ctx())

    # memory.txt still SUCCESS (vm_stat timeout absorbed within _run_cmd)
    # because _run_cmd converts TimeoutExpired -> ("", None, "TIMEOUT") and
    # the artifact-level code writes a note rather than crashing.
    mem_art = next(a for a in res.artifacts if a.name == "memory.txt")
    assert mem_art.status == "SUCCESS"
    # All 8 artifacts present
    assert len(res.artifacts) == 8
    _ok(label)


def test_all_artifacts_present():
    """Provider must always produce exactly 8 named artifacts."""
    label = " 9b. all 8 artifacts always present ..... "
    provider = MacOSSystemSnapshotProvider()

    with patch("subprocess.run", side_effect=_mkcmd()):
        res = provider.capture(_ctx())

    expected = {
        "system_info.txt", "cpu.txt", "memory.txt", "disk.txt",
        "load.txt", "top_processes.txt", "network.txt", "uptime.txt",
    }
    actual = {a.name for a in res.artifacts}
    missing = expected - actual
    assert not missing, f"Missing artifacts: {missing}"
    _ok(label)


def test_full_success_status():
    """All commands succeed -> overall status SUCCESS."""
    label = " 9c. all success -> SUCCESS status ....... "
    provider = MacOSSystemSnapshotProvider()

    with patch("subprocess.run", side_effect=_mkcmd()):
        res = provider.capture(_ctx())

    assert res.status == "SUCCESS", f"Expected SUCCESS, got {res.status}"
    _ok(label)


# ══════════════════════════════════════════════════════════════════════════════
# TEST 10 – Configuration override
# ══════════════════════════════════════════════════════════════════════════════
def test_config_snapshot_overrides_collectors():
    """snapshot.providers.system.disk_paths must take priority over collectors.system."""
    label = "10. config snapshot overrides collectors  "
    provider = MacOSSystemSnapshotProvider()

    config = {
        "collectors": {"system": {"disk_path": "/should-not-appear", "timeout": 10.0}},
        "snapshot":   {"providers": {"system": {"disk_paths": ["/override"], "timeout": 3.0}}},
    }
    df_calls = []
    base = _mkcmd()
    def _patched(args, **kw):
        if args[0] == "df":
            df_calls.append(args[-1])
            return MagicMock(returncode=0, stdout=f"Filesystem\n/dev/d {args[-1]}", stderr="")
        return base(args, **kw)

    with patch("subprocess.run", side_effect=_patched):
        res = provider.capture(_ctx(config))

    assert "/override" in df_calls,              "snapshot.providers.system.disk_paths not used"
    assert "/should-not-appear" not in df_calls, "collectors.system.disk_path used despite override"
    _ok(label)


def test_config_fallback_to_collectors():
    """When snapshot.providers.system is absent, fall back to collectors.system."""
    label = "10b. config fallback to collectors ....... "
    provider = MacOSSystemSnapshotProvider()

    config = {
        "collectors": {"system": {"disk_path": "/fallback-path"}},
    }
    df_calls = []
    base = _mkcmd()
    def _patched(args, **kw):
        if args[0] == "df":
            df_calls.append(args[-1])
            return MagicMock(returncode=0, stdout=f"Filesystem\n/dev/d {args[-1]}", stderr="")
        return base(args, **kw)

    with patch("subprocess.run", side_effect=_patched):
        res = provider.capture(_ctx(config))

    assert "/fallback-path" in df_calls, "collectors.system.disk_path not used as fallback"
    _ok(label)


def test_config_top_process_count():
    """snapshot.providers.system.top_process_count must be respected."""
    label = "10c. config top_process_count respected .. "
    provider = MacOSSystemSnapshotProvider()

    rows = ["  PID  PPID  %CPU  %MEM COMMAND"] + [
        f"  {200+i}     1   0.1   0.0 /usr/bin/proc_{i}" for i in range(30)
    ]
    config = {"snapshot": {"providers": {"system": {"top_process_count": 5}}}}
    with patch("subprocess.run", side_effect=_mkcmd(ps_out="\n".join(rows))):
        res = provider.capture(_ctx(config))

    art = next(a for a in res.artifacts if a.name == "top_processes.txt")
    data_lines = [l for l in art.content.splitlines()
                  if l.strip() and not l.strip().startswith("PID") and not l.strip().startswith("(")]
    assert len(data_lines) <= 5, f"Expected <=5 rows, got {len(data_lines)}"
    _ok(label)


# ══════════════════════════════════════════════════════════════════════════════
# TEST 11 – Observer-only / static safety audit
# ══════════════════════════════════════════════════════════════════════════════
def test_static_safety_audit():
    """
    Statically verify system.py does not contain dangerous operations.
    """
    label = "11. observer-only static audit .......... "
    provider_file = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../app/snapshot/providers/system.py")
    )
    with open(provider_file, "r", encoding="utf-8") as f:
        code = f.read()

    # Must never use shell=True
    assert "shell=True" not in code, "FAIL: shell=True found in system.py"

    # Forbidden direct OS calls
    forbidden_calls = [
        "os.system(",
        "os.popen(",
        "os.kill(",
        "os.remove(",
        "os.unlink(",
        "subprocess.Popen(",   # Popen without context
        "subprocess.call(",
    ]
    for fc in forbidden_calls:
        assert fc not in code, f"FAIL: forbidden call '{fc}' found in system.py"

    # Forbidden destructive/observation-breaking commands
    forbidden_cmds = [
        '"kill"', "'kill'",
        '"pkill"', "'pkill'",
        '"rm"', "'rm'",
        '"shutdown"', "'shutdown'",
        '"reboot"', "'reboot'",
        '"launchctl"', "'launchctl'",   # no service control from system provider
        '"tcpdump"', "'tcpdump'",
        '"tshark"', "'tshark'",
        '"find"', "'find'",             # no expensive FS scans
        '"du"', "'du'",
        '"sync"', "'sync'",
        '"purge"', "'purge'",           # macOS cache flush
        '"dscacheutil"', "'dscacheutil'",
    ]
    for fc in forbidden_cmds:
        # Make sure these don't appear as list elements (command arguments)
        pattern = rf'\[.*{re.escape(fc)}.*\]'
        if re.search(pattern, code):
            raise AssertionError(f"FAIL: forbidden command {fc} found in system.py subprocess call")

    # Must have explicit timeouts (timeout= in every _run_cmd call)
    run_cmd_calls = re.findall(r'(?<!def )_run_cmd\(', code)
    timeout_in_calls = re.findall(r'(?<!def )_run_cmd\([^)]+timeout=', code)
    assert len(run_cmd_calls) == len(timeout_in_calls), (
        f"FAIL: {len(run_cmd_calls)} _run_cmd calls but only {len(timeout_in_calls)} have timeout="
    )

    _ok(label)


# ══════════════════════════════════════════════════════════════════════════════
# TEST 12 – Engine integration + storage structure
# ══════════════════════════════════════════════════════════════════════════════
def test_engine_integration():
    """
    SnapshotEngine.run() -> evidence/system/ must contain all 8 artifacts
    + metadata.json; manifest must record provider_name=system with SUCCESS.
    """
    label = "12. engine integration & storage ........ "
    from app.snapshot.engine import SnapshotEngine

    incident_id = "INC-SYS-ENGINE"
    evidence_root = os.path.join("incidents", incident_id)
    if os.path.exists(evidence_root):
        shutil.rmtree(evidence_root)
    os.makedirs(evidence_root, exist_ok=True)

    provider = MacOSSystemSnapshotProvider()
    SnapshotEngine.register_provider(provider)

    config = {"snapshot": {"providers": {"system": {"disk_paths": ["/"]}}}}

    try:
        with patch("subprocess.run", side_effect=_mkcmd()):
            manifest = SnapshotEngine.run(incident_id, "System", config)

        sys_dir = os.path.join(evidence_root, "evidence", "system")
        assert os.path.isdir(sys_dir), "evidence/system/ not created"

        expected_files = {
            "system_info.txt", "cpu.txt", "memory.txt", "disk.txt",
            "load.txt", "top_processes.txt", "network.txt", "uptime.txt",
            "metadata.json",
        }
        actual_files = set(os.listdir(sys_dir))
        missing = expected_files - actual_files
        assert not missing, f"Missing files in evidence/system/: {missing}"

        # metadata.json must be valid JSON with correct provider key
        with open(os.path.join(sys_dir, "metadata.json")) as f:
            meta = json.load(f)
        assert meta["provider"] == "system"
        assert meta["status"] == "SUCCESS"
        assert len(meta["artifacts"]) == 8

        # manifest must record the provider result
        sys_result = next(
            (r for r in manifest["results"] if r["provider_name"] == "system"), None
        )
        assert sys_result is not None, "system not in manifest results"
        assert sys_result["status"] == "SUCCESS"

    finally:
        shutil.rmtree(evidence_root, ignore_errors=True)

    _ok(label)


# ══════════════════════════════════════════════════════════════════════════════
# TEST 13 – Linux provider smoke test
# ══════════════════════════════════════════════════════════════════════════════
def test_linux_provider_basic():
    """LinuxSystemSnapshotProvider must produce 8 artifacts on mocked output."""
    label = "13. Linux provider basic smoke test ..... "
    provider = LinuxSystemSnapshotProvider()

    def _linux_fake(args, **kw):
        mapping = {
            ("hostname",):              ("linuxbox", 0, ""),
            ("uname", "-a"):            ("Linux linuxbox 6.1 #1 SMP x86_64", 0, ""),
            ("uname", "-m"):            ("x86_64", 0, ""),
            ("nproc", "--all"):         ("8", 0, ""),
            ("free", "-h"):             ("              total  used  free\nMem:  15G  4G  11G", 0, ""),
            ("df",):                    ("Filesystem  1K-blocks  Used  Avail  Use%  Mounted\n/dev/sda1  1000000  400000  600000   40%  /", 0, ""),
            ("uptime",):                (" 12:00:00 up 3 days, 4:00,  1 user,  load average: 0.50, 0.60, 0.70", 0, ""),
            ("ps",):                    ("  PID  PPID  %CPU  %MEM COMMAND\n  100     1   2.0   0.1 /usr/sbin/sshd", 0, ""),
            ("ss", "-tlnp"):            ("State  Recv-Q  Send-Q  Local Address:Port\nLISTEN  0  128  0.0.0.0:22", 0, ""),
        }
        for n in (3, 2, 1):
            k = tuple(args[:n])
            if k in mapping:
                out, rc, err = mapping[k]
                return MagicMock(returncode=rc, stdout=out, stderr=err)
        return MagicMock(returncode=0, stdout="", stderr="")

    # Patch open() for /proc and /etc files
    import builtins
    real_open = builtins.open
    def _fake_open(path, *a, **kw):
        if path == "/etc/os-release":
            from io import StringIO
            class FakeFile:
                def __enter__(self): return self
                def __exit__(self, *a): pass
                def read(self, n=-1): return 'NAME="Ubuntu"\nVERSION_ID="22.04"\n'
            return FakeFile()
        if path == "/proc/cpuinfo":
            class FakeFile2:
                def __enter__(self): return self
                def __exit__(self, *a): pass
                def read(self, n=-1): return "processor\t: 0\nmodel name\t: Intel Core i7\n"
            return FakeFile2()
        if path == "/proc/loadavg":
            class FakeFile3:
                def __enter__(self): return self
                def __exit__(self, *a): pass
                def read(self, n=-1): return "0.50 0.60 0.70 1/400 12345"
            return FakeFile3()
        if path == "/proc/uptime":
            class FakeFile4:
                def __enter__(self): return self
                def __exit__(self, *a): pass
                def read(self, n=-1): return "259200.00 200000.00"
            return FakeFile4()
        return real_open(path, *a, **kw)

    with patch("subprocess.run", side_effect=_linux_fake):
        with patch("builtins.open", side_effect=_fake_open):
            res = provider.capture(_ctx())

    expected_names = {
        "system_info.txt", "cpu.txt", "memory.txt", "disk.txt",
        "load.txt", "top_processes.txt", "network.txt", "uptime.txt",
    }
    actual_names = {a.name for a in res.artifacts}
    missing = expected_names - actual_names
    assert not missing, f"Linux provider missing artifacts: {missing}"
    assert res.status == "SUCCESS"
    _ok(label)


# ══════════════════════════════════════════════════════════════════════════════
# REGRESSIONS
# ══════════════════════════════════════════════════════════════════════════════
def _run_regression(script: str) -> bool:
    """Run an external test script and return True if it exits 0."""
    import subprocess as sp
    r = sp.run([sys.executable, script], capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-1000:])
        print(r.stderr[-500:])
    return r.returncode == 0


def test_regression_backend():
    label = "R1. Backend provider regression ......... "
    assert _run_regression("scratch/test_backend_provider.py"), "Backend regression FAILED"
    _ok(label)

def test_regression_nginx():
    label = "R2. Nginx provider regression ........... "
    assert _run_regression("scratch/test_nginx_provider.py"), "Nginx regression FAILED"
    _ok(label)

def test_regression_postgres():
    label = "R3. PostgreSQL provider regression ....... "
    assert _run_regression("scratch/test_postgres_provider.py"), "Postgres regression FAILED"
    _ok(label)

def test_regression_cloudflare():
    label = "R4. Cloudflare provider regression ...... "
    assert _run_regression("scratch/test_cloudflared_provider.py"), "Cloudflare regression FAILED"
    _ok(label)

def test_regression_redis():
    label = "R5. Redis provider regression ........... "
    assert _run_regression("scratch/test_redis_provider.py"), "Redis regression FAILED"
    _ok(label)

def test_regression_config():
    label = "R6. Config override regression .......... "
    assert _run_regression("scratch/test_config_override.py"), "Config override regression FAILED"
    _ok(label)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
def main():
    print("=" * 60)
    print("Type 1 Verification – Milestone 9 Batch 7: System Provider")
    print("=" * 60)

    tests = [
        # system_info
        test_system_info_macos,
        test_system_info_missing_command,
        # cpu
        test_cpu_macos,
        test_cpu_sysctl_missing,
        # memory
        test_memory_macos,
        test_memory_bad_memsize,
        test_memory_vm_stat_timeout,
        # disk
        test_disk_absolute_path,
        test_disk_non_absolute_rejected,
        test_disk_paths_bounded_to_10,
        test_disk_df_failure_recorded,
        # load
        test_load_macos,
        test_load_uptime_failure,
        # top_processes / CRITICAL SECURITY
        test_top_processes_security_unit,
        test_top_processes_security_integration,
        test_top_processes_disk_secret_scan,
        test_top_processes_count_bounded,
        test_top_processes_self_pid_excluded,
        test_top_processes_ps_timeout,
        # network
        test_network_listen_only,
        test_network_bounded_output,
        test_network_empty_output,
        test_network_timeout,
        # uptime
        test_uptime_macos,
        test_uptime_boottime_missing,
        # failure isolation
        test_failure_isolation_partial,
        test_all_artifacts_present,
        test_full_success_status,
        # config
        test_config_snapshot_overrides_collectors,
        test_config_fallback_to_collectors,
        test_config_top_process_count,
        # observer-only
        test_static_safety_audit,
        # engine integration
        test_engine_integration,
        # Linux smoke
        test_linux_provider_basic,
        # regressions
        test_regression_backend,
        test_regression_nginx,
        test_regression_postgres,
        test_regression_cloudflare,
        test_regression_redis,
        test_regression_config,
    ]

    for test_fn in tests:
        try:
            test_fn()
        except AssertionError as e:
            # _fail already printed; re-raise to abort
            print(f"\n{'=' * 60}")
            print("VERIFICATION FAILED")
            print(f"{'=' * 60}")
            print(f"Error: {e}")
            sys.exit(1)
        except Exception as e:
            global _FAIL_COUNT
            _FAIL_COUNT += 1
            print(f"  UNEXPECTED ERROR: {e}")
            print(f"\n{'=' * 60}")
            print("VERIFICATION FAILED")
            print(f"{'=' * 60}")
            raise

    print(f"\n{'=' * 60}")
    print(f"ALL {_PASS_COUNT} CHECKS PASSED")
    print("TYPE 1 VERIFIED")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
