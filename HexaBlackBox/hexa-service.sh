#!/bin/bash

# HexaBlackBox Service Management Script
# Provides lifecycle control triggers and configuration setup for the background daemon.

PLIST_LABEL="com.hexablackbox.monitor"
PLIST_FILE="${HOME}/Library/LaunchAgents/${PLIST_LABEL}.plist"
TEMPLATE_FILE="config/com.hexablackbox.monitor.plist.template"
USER_ID=$(id -u)

# Resolve script folder and project root dynamically
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
WORKING_DIR="${SCRIPT_DIR}"

# Detect project virtual environment parent-folder location
PYTHON_PATH="$(dirname "${WORKING_DIR}")/venv/bin/python"
if [ ! -f "${PYTHON_PATH}" ]; then
    # Fallback to Windows virtual environment binary structure if running locally
    PYTHON_PATH="$(dirname "${WORKING_DIR}")/venv/Scripts/python.exe"
fi

# Colors for operator-friendly output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0;0m' # Normal Color

show_usage() {
    echo "Usage: $0 {install|uninstall|start|stop|restart|reload|status|verify|logs}"
    exit 1
}

if [ $# -lt 1 ]; then
    show_usage
fi

case "$1" in
    install)
        echo "Installing HexaBlackBox Service..."
        
        # Enforce that the project virtual environment must exist
        if [ ! -f "${PYTHON_PATH}" ]; then
            echo -e "${RED}Error: Virtual environment python interpreter not found at parent venv directory: $(dirname "${WORKING_DIR}")/venv/${NC}"
            exit 1
        fi
        
        # Ensure logs directory exists
        mkdir -p "${WORKING_DIR}/logs"
        
        # Build plist from template
        sed -e "s|{{WORKING_DIR}}|${WORKING_DIR}|g" \
            -e "s|{{PYTHON_PATH}}|${PYTHON_PATH}|g" \
            "${TEMPLATE_FILE}" > "${PLIST_FILE}"
            
        chmod 644 "${PLIST_FILE}"
        echo "Plist created: ${PLIST_FILE}"
        
        # Load plist using modern bootstrap
        launchctl bootstrap gui/"${USER_ID}" "${PLIST_FILE}"
        echo -e "${GREEN}Service installed and loaded successfully.${NC}"
        ;;
        
    uninstall)
        echo "Uninstalling HexaBlackBox Service..."
        if [ -f "${PLIST_FILE}" ]; then
            launchctl bootout gui/"${USER_ID}" "${PLIST_FILE}" 2>/dev/null || true
            rm "${PLIST_FILE}"
            echo -e "${GREEN}Service uninstalled successfully.${NC}"
        else
            echo "Service plist not found. Nothing to uninstall."
        fi
        ;;
        
    start)
        echo "Starting HexaBlackBox Service..."
        if [ -f "${PLIST_FILE}" ]; then
            # Bootstrap if not loaded, kickstart if already loaded
            launchctl bootstrap gui/"${USER_ID}" "${PLIST_FILE}" 2>/dev/null || \
            launchctl kickstart gui/"${USER_ID}"/"${PLIST_LABEL}"
            echo -e "${GREEN}Service start request sent.${NC}"
        else
            echo -e "${RED}Error: Plist not installed. Run: $0 install${NC}"
        fi
        ;;
        
    stop)
        echo "Stopping HexaBlackBox Service..."
        if [ -f "${PLIST_FILE}" ]; then
            # NOTE: Directly terminating the python process is insufficient because
            # the KeepAlive key in the LaunchAgent config tells launchd to automatically
            # restart the process. Unloading via bootout is the correct way to stop
            # and keep the daemon stopped without triggering automatic recovery.
            launchctl bootout gui/"${USER_ID}" "${PLIST_FILE}"
            echo -e "${GREEN}Service stopped (booted out).${NC}"
        else
            echo -e "${RED}Error: Plist not installed.${NC}"
        fi
        ;;
        
    restart)
        echo "Restarting HexaBlackBox Service..."
        if [ -f "${PLIST_FILE}" ]; then
            launchctl kickstart -k gui/"${USER_ID}"/"${PLIST_LABEL}"
            echo -e "${GREEN}Service restarted successfully.${NC}"
        else
            echo -e "${RED}Error: Plist not installed.${NC}"
        fi
        ;;
        
    reload)
        echo "Reloading HexaBlackBox Service..."
        if [ -f "${PLIST_FILE}" ]; then
            launchctl bootout gui/"${USER_ID}" "${PLIST_FILE}" 2>/dev/null || true
            launchctl bootstrap gui/"${USER_ID}" "${PLIST_FILE}"
            echo -e "${GREEN}Service reloaded (re-bootstrapped).${NC}"
        else
            echo -e "${RED}Error: Plist not installed.${NC}"
        fi
        ;;
        
    status)
        echo -e "--- Service Operational Status ---"
        
        # Plist installation status
        if [ -f "${PLIST_FILE}" ]; then
            echo -e "LaunchAgent Plist .... Installed (${PLIST_FILE})"
        else
            echo -e "LaunchAgent Plist .... Not Installed"
        fi
        
        echo -e "Working Directory .... ${WORKING_DIR}"
        echo -e "Python Interpreter ... ${PYTHON_PATH}"
        echo -e "Stdout Log Path ...... ${WORKING_DIR}/logs/service_stdout.log"
        echo -e "Stderr Log Path ...... ${WORKING_DIR}/logs/service_stderr.log"
        
        # Running status check
        if [ -f "${PLIST_FILE}" ]; then
            status_info=$(launchctl list | grep "${PLIST_LABEL}")
            if [ -n "${status_info}" ]; then
                pid=$(echo "${status_info}" | awk '{print $1}')
                exit_code=$(echo "${status_info}" | awk '{print $2}')
                
                if [ "${pid}" != "-" ] && [ "${pid}" -gt 0 ]; then
                    echo -e "Daemon Status ........ ${GREEN}RUNNING (PID: ${pid})${NC}"
                else
                    echo -e "Daemon Status ........ ${RED}LOADED but STOPPED (Last Exit Code: ${exit_code})${NC}"
                fi
            else
                echo -e "Daemon Status ........ ${RED}NOT LOADED in launchd${NC}"
            fi
        else
            echo -e "Daemon Status ........ ${RED}NOT INSTALLED${NC}"
        fi
        ;;
        
    verify)
        echo -e "--- Starting Deployment Verification ---"
        has_errors=0
        
        # 1. Check working directory
        if [ -d "${WORKING_DIR}" ]; then
            echo -e "[PASS] Working directory exists: ${WORKING_DIR}"
        else
            echo -e "[FAIL] Working directory does not exist: ${WORKING_DIR}"
            has_errors=1
        fi
        
        # 2. Check template file
        if [ -f "${TEMPLATE_FILE}" ]; then
            echo -e "[PASS] LaunchAgent template plist exists"
        else
            echo -e "[FAIL] LaunchAgent template plist missing: ${TEMPLATE_FILE}"
            has_errors=1
        fi
        
        # 3. Check generated plist and syntax
        if [ -f "${PLIST_FILE}" ]; then
            echo -e "[PASS] Generated LaunchAgent plist exists: ${PLIST_FILE}"
            
            # Syntax validation via plutil
            if which plutil >/dev/null 2>&1; then
                if plutil -lint "${PLIST_FILE}" >/dev/null 2>&1; then
                    echo -e "[PASS] Plist syntax syntax-check passed (plutil)"
                else
                    echo -e "[FAIL] Plist syntax syntax-check failed (plutil)"
                    has_errors=1
                fi
            else
                echo -e "[WARN] plutil tool not found, skipping syntax check"
            fi
        else
            echo -e "[WARN] Generated plist not found (not installed yet)"
        fi
        
        # 4. Check python path
        if [ -f "${PYTHON_PATH}" ]; then
            echo -e "[PASS] Virtual environment python interpreter exists: ${PYTHON_PATH}"
        else
            echo -e "[FAIL] Virtual environment python interpreter missing at: ${PYTHON_PATH}"
            has_errors=1
        fi
        
        # 5. Check log folders/files
        mkdir -p "${WORKING_DIR}/logs"
        if [ -w "${WORKING_DIR}/logs" ]; then
            echo -e "[PASS] Logs directory exists and is writable"
        else
            echo -e "[FAIL] Logs directory is not writable"
            has_errors=1
        fi
        
        echo -e "\n--- Verification Summary ---"
        if [ ${has_errors} -eq 0 ]; then
            echo -e "${GREEN}ALL CHECKS PASSED: Environment is verified.${NC}"
        else
            echo -e "${RED}CHECKS FAILED: Please fix configuration issues.${NC}"
            exit 1
        fi
        ;;
        
    logs)
        echo "Tailing HexaBlackBox service logs..."
        tail -f logs/service_stdout.log logs/service_stderr.log
        ;;
        
    *)
        show_usage
        ;;
esac
