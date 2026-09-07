#!/bin/bash
# =========================================================
# HexaMonitor — Firewall Setup Script
# =========================================================
# Installs a dedicated pf anchor to restrict TCP port 8000
# to loopback and the GCP Tailscale IP only.
#
# Usage:  sudo bash deployment/setup_firewall.sh
#
# This script:
#   1. Copies the anchor rules to /etc/pf.anchors/com.hexamonitor
#   2. Adds the anchor reference to /etc/pf.conf (if not already present)
#   3. Reloads pf rules
#
# It does NOT overwrite /etc/pf.conf — it only appends an anchor line.
# =========================================================

set -euo pipefail

ANCHOR_NAME="com.hexamonitor"
ANCHOR_FILE="/etc/pf.anchors/${ANCHOR_NAME}"
PF_CONF="/etc/pf.conf"
SOURCE_RULES="$(cd "$(dirname "$0")" && pwd)/hexamonitor_firewall.conf"

# Must run as root
if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: This script must be run as root (sudo)."
    exit 1
fi

echo "=== HexaMonitor Firewall Setup ==="

# 1. Copy anchor rules
echo "[1/3] Installing anchor rules to ${ANCHOR_FILE}..."
cp "${SOURCE_RULES}" "${ANCHOR_FILE}"
chmod 644 "${ANCHOR_FILE}"
echo "      Done."

# 2. Add anchor reference to /etc/pf.conf if not present
if grep -q "anchor \"${ANCHOR_NAME}\"" "${PF_CONF}" 2>/dev/null; then
    echo "[2/3] Anchor reference already exists in ${PF_CONF}. Skipping."
else
    echo "[2/3] Adding anchor reference to ${PF_CONF}..."
    # Back up pf.conf before modifying
    cp "${PF_CONF}" "${PF_CONF}.hexamonitor-backup-$(date +%Y%m%d%H%M%S)"
    # Insert the anchor lines BEFORE the com.apple anchor (so our rules evaluate first)
    # If com.apple anchor not found, append to end
    if grep -q 'anchor "com.apple/\*"' "${PF_CONF}"; then
        # Insert our anchor just before the com.apple anchor line
        sed -i '' '/^anchor "com\.apple\/\*"/i\
anchor "'"${ANCHOR_NAME}"'"\
load anchor "'"${ANCHOR_NAME}"'" from "'"${ANCHOR_FILE}"'"\
' "${PF_CONF}"
    else
        # Fallback: append to end of file
        echo "" >> "${PF_CONF}"
        echo "anchor \"${ANCHOR_NAME}\"" >> "${PF_CONF}"
        echo "load anchor \"${ANCHOR_NAME}\" from \"${ANCHOR_FILE}\"" >> "${PF_CONF}"
    fi
    echo "      Done."
fi

# 3. Reload pf rules
echo "[3/3] Reloading pf rules..."
pfctl -f "${PF_CONF}" 2>/dev/null || true
pfctl -E 2>/dev/null || true
echo "      Done."

echo ""
echo "=== Firewall Setup Complete ==="
echo "Verifying loaded rules for anchor ${ANCHOR_NAME}:"
pfctl -a "${ANCHOR_NAME}" -sr 2>/dev/null || echo "(Anchor rules will load on next pf enable)"
echo ""
echo "Access policy:"
echo "  ✅ 127.0.0.1:8000       — ALLOWED (loopback)"
echo "  ✅ 100.70.10.23 → :8000 — ALLOWED (GCP Tailscale)"
echo "  ❌ All other → :8000    — BLOCKED"
