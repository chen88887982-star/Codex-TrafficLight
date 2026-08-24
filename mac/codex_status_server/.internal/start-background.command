#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUNTIME_DIR="${SERVICE_DIR}/.runtime"
PORT="${PORT:-8767}"
HOST="${HOST:-127.0.0.1}"
HEALTH_URL="http://127.0.0.1:${PORT}/health"
EXPECTED_SERVICE="codex-traffic-light-status"
STDOUT_FILE="${RUNTIME_DIR}/status-server-output.log"
STDERR_FILE="${RUNTIME_DIR}/status-server-error.log"

mkdir -p "$RUNTIME_DIR"
for filename in status.json usage-cache.json status-server.log status-server-output.log status-server-error.log status-server.pid; do
  if [ -f "${SERVICE_DIR}/${filename}" ] && [ ! -e "${RUNTIME_DIR}/${filename}" ]; then
    mv "${SERVICE_DIR}/${filename}" "${RUNTIME_DIR}/${filename}"
  fi
done

health_ok() {
  local payload
  payload="$(curl --silent --show-error --fail --max-time 2 "$HEALTH_URL" 2>/dev/null)" || return 1
  printf '%s' "$payload" | python3 -c 'import json,sys; d=json.load(sys.stdin); raise SystemExit(0 if d.get("service")=="codex-traffic-light-status" and d.get("status") in {"ok","degraded","error"} else 1)'
}

if health_ok; then
  echo "[OK] Status service is already running on port ${PORT}; no duplicate was started."
  exit 0
fi

if command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:"${PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "[ERROR] Port ${PORT} is occupied by another service." >&2
  exit 1
fi

PYTHON_BIN="${SERVICE_DIR}/../../.venv/bin/python3"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="$(command -v python3 || true)"
fi
if [ -z "$PYTHON_BIN" ]; then
  echo "[ERROR] Python 3 was not found." >&2
  exit 1
fi

export HOST PORT
export CODEX_COMMAND="${CODEX_COMMAND:-/Applications/ChatGPT.app/Contents/Resources/codex}"
nohup "$PYTHON_BIN" "${SCRIPT_DIR}/server.py" >>"$STDOUT_FILE" 2>>"$STDERR_FILE" </dev/null &
LAUNCH_PID=$!

for ((attempt=0; attempt<40; attempt++)); do
  if health_ok; then
    SERVICE_PID="$(sed -n 's/.*"pid": \([0-9][0-9]*\).*/\1/p' "${RUNTIME_DIR}/status-server.pid" | head -n 1)"
    echo "[OK] Status service is running in the background (PID ${SERVICE_PID:-$LAUNCH_PID})."
    exit 0
  fi
  if ! kill -0 "$LAUNCH_PID" 2>/dev/null; then
    echo "[ERROR] Status service exited during startup. See ${STDERR_FILE}." >&2
    exit 1
  fi
  sleep 0.5
done

kill "$LAUNCH_PID" 2>/dev/null || true
echo "[ERROR] Status service did not pass its health check within 20 seconds." >&2
exit 1
