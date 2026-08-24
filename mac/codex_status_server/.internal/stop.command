#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PID_FILE="${SERVICE_DIR}/.runtime/status-server.pid"
SERVER_FILE="${SCRIPT_DIR}/server.py"

if [ ! -f "$PID_FILE" ]; then
  echo "[OK] No status-service PID file was found."
  exit 0
fi
PID="$(sed -n 's/.*"pid": \([0-9][0-9]*\).*/\1/p' "$PID_FILE" | head -n 1)"
if [ -z "$PID" ]; then
  echo "[ERROR] The PID file is invalid; no process was stopped." >&2
  exit 1
fi
if ! kill -0 "$PID" 2>/dev/null; then
  rm -f "$PID_FILE"
  echo "[OK] The recorded service is no longer running."
  exit 0
fi
COMMAND="$(ps -p "$PID" -o command= 2>/dev/null || true)"
case "$COMMAND" in
  *"$SERVER_FILE"*) ;;
  *)
    echo "[ERROR] PID ${PID} belongs to another process; nothing was stopped." >&2
    exit 1
    ;;
esac
kill "$PID"
for ((attempt=0; attempt<20; attempt++)); do
  kill -0 "$PID" 2>/dev/null || break
  sleep 0.1
done
if kill -0 "$PID" 2>/dev/null; then
  echo "[ERROR] Service PID ${PID} did not stop in time." >&2
  exit 1
fi
rm -f "$PID_FILE"
echo "[OK] Stopped status service PID ${PID}."
