import sys
import os
import subprocess

# Adjust search path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

def test_plist_template_integrity():
    print("Plist Template XML Verification ...... ", end="", flush=True)
    template_path = "config/com.hexablackbox.monitor.plist.template"
    assert os.path.exists(template_path), "Template plist missing!"
    
    with open(template_path, "r") as f:
        content = f.read()
    
    # Check placeholders are present
    assert "{{PYTHON_PATH}}" in content, "Missing python path placeholder"
    assert "{{WORKING_DIR}}" in content, "Missing working directory placeholder"
    
    # Basic XML structure checks
    assert "<plist" in content
    assert "<dict>" in content
    assert "</plist>" in content
    
    print("PASSED")

def test_script_syntax_and_executability():
    print("Shell Script syntax Check ........... ", end="", flush=True)
    script_path = "./hexa-service.sh"
    assert os.path.exists(script_path), "hexa-service.sh is missing!"
    
    # Shell check syntax using bash -n (dry run syntax compilation check)
    try:
        res = subprocess.run(["bash", "-n", script_path], capture_output=True, text=True)
        assert res.returncode == 0, f"Syntax compilation errors found:\n{res.stderr}"
        print("PASSED")
    except FileNotFoundError:
        # Bash not present (e.g. Windows raw cmd), verify basic file formatting
        with open(script_path, "r") as f:
            lines = f.readlines()
        assert lines[0].startswith("#!/bin/bash"), "Invalid shebang header!"
        print("PASSED (Fallback String Check)")

def test_verify_command_execution():
    print("Verify Command dry-run Check ........ ", end="", flush=True)
    # Check that verify command runs and outputs valid parameters
    try:
        res = subprocess.run(["bash", "./hexa-service.sh", "verify"], capture_output=True, text=True)
        # Note: it will print warnings/passes to stdout/stderr.
        # We verify that standard execution flows cleanly
        assert "Verification" in res.stdout
        assert "Summary" in res.stdout
        print("PASSED")
    except FileNotFoundError:
        print("SKIPPED (Bash command unavailable on environment)")

def main():
    print("==================================================")
    print("Starting Type 1 Verification (Milestone 7)")
    print("==================================================")
    try:
        test_plist_template_integrity()
        test_script_syntax_and_executability()
        test_verify_command_execution()
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
