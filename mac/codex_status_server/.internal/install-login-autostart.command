#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
LABEL="com.codex.trafficlight.status"
PLIST_DIR="${HOME}/Library/LaunchAgents"
PLIST_PATH="${PLIST_DIR}/${LABEL}.plist"
START_SCRIPT="${SERVICE_DIR}/启动状态服务.command"
mkdir -p "$PLIST_DIR"
python3 - "$PLIST_PATH" "$START_SCRIPT" "$SCRIPT_DIR" <<'PY'
import plistlib
import sys
from pathlib import Path
path, start_script, workdir = sys.argv[1:]
payload = {
    "Label": "com.codex.trafficlight.status",
    "ProgramArguments": ["/bin/bash", start_script],
    "WorkingDirectory": workdir,
    "RunAtLoad": True,
    "ProcessType": "Background",
    "StandardOutPath": str(Path(workdir).parent / ".runtime" / "launch-agent-output.log"),
    "StandardErrorPath": str(Path(workdir).parent / ".runtime" / "launch-agent-error.log"),
}
with open(path, "wb") as handle:
    plistlib.dump(payload, handle, sort_keys=False)
PY
DOMAIN="gui/$(id -u)"
launchctl bootout "$DOMAIN" "$PLIST_PATH" >/dev/null 2>&1 || true
launchctl bootstrap "$DOMAIN" "$PLIST_PATH"
launchctl enable "${DOMAIN}/${LABEL}"
launchctl kickstart -k "${DOMAIN}/${LABEL}"
echo "[OK] Installed login startup agent: ${LABEL}"
