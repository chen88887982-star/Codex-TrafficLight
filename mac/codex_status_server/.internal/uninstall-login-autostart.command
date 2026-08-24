#!/usr/bin/env bash
set -euo pipefail
LABEL="com.codex.trafficlight.status"
PLIST_PATH="${HOME}/Library/LaunchAgents/${LABEL}.plist"
DOMAIN="gui/$(id -u)"
launchctl bootout "$DOMAIN" "$PLIST_PATH" >/dev/null 2>&1 || true
rm -f "$PLIST_PATH"
echo "[OK] Removed login startup agent: ${LABEL}"
