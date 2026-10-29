#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUNTIME_DIR="${SERVICE_DIR}/.runtime"
PYTHON_BIN="${SERVICE_DIR}/../../.venv/bin/python3"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="$(command -v python3 || true)"
fi
if [ -z "$PYTHON_BIN" ]; then
  echo "[ERROR] Python 3 was not found." >&2
  exit 1
fi
SAVED_SETTINGS="$("$PYTHON_BIN" - "${RUNTIME_DIR}/launch-settings.json" <<'SETTINGS'
import json, sys
from pathlib import Path
host, port = "0.0.0.0", 8767
try:
    saved = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    if not isinstance(saved, dict):
        raise ValueError("invalid launch settings")
    candidate = saved.get("host", "")
    if not isinstance(candidate, str):
        candidate = ""
    if candidate and all(c.isalnum() or c in ".:_-" for c in candidate):
        host = candidate
    candidate_port = int(saved.get("port", 8767))
    if 1 <= candidate_port <= 65535:
        port = candidate_port
except (OSError, ValueError, TypeError):
    pass
print(host, port)
SETTINGS
)"
SAVED_HOST="${SAVED_SETTINGS% *}"
SAVED_PORT="${SAVED_SETTINGS##* }"
PORT="${PORT:-${CODEX_STATUS_PORT:-$SAVED_PORT}}"
HOST="${HOST:-$SAVED_HOST}"
HEALTH_URL="http://127.0.0.1:${PORT}/health"
EXPECTED_SERVICE="codex-traffic-light-status"
STDOUT_FILE="${RUNTIME_DIR}/status-server-output.log"
STDERR_FILE="${RUNTIME_DIR}/status-server-error.log"

mkdir -p "$RUNTIME_DIR"
LEGACY_DIR="${RUNTIME_DIR}/legacy-$(date +%Y%m%d-%H%M%S)"
for legacy in "${SERVICE_DIR}"/status.json "${SERVICE_DIR}"/usage-cache.json "${SERVICE_DIR}"/status-server.log* "${SERVICE_DIR}"/status-server-output.log "${SERVICE_DIR}"/status-server-error.log "${SERVICE_DIR}"/status-server.pid; do
  [ -f "$legacy" ] || continue
  filename="$(basename "$legacy")"
  target="${RUNTIME_DIR}/${filename}"
  if [ ! -e "$target" ] && [[ ! "$filename" =~ ^status-server\.log\.[0-9]+$ ]]; then
    mv "$legacy" "$target"
  else
    mkdir -p "$LEGACY_DIR"
    mv "$legacy" "${LEGACY_DIR}/${filename}"
  fi
done

health_ok() {
  local payload
  payload="$(curl --silent --show-error --fail --max-time 2 "$HEALTH_URL" 2>/dev/null)" || return 1
  printf '%s' "$payload" | "$PYTHON_BIN" -c 'import json,sys; d=json.load(sys.stdin); ok=d.get("service")=="codex-traffic-light-status" and d.get("service_version")=="0.5.1" and d.get("protocol_version")==2 and d.get("status") in {"ok","degraded","error"}; raise SystemExit(0 if ok else 1)'
}

if health_ok; then
  echo "[OK] Status service is already running on port ${PORT}; no duplicate was started."
  exit 0
fi

if command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:"${PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "[ERROR] Port ${PORT} is occupied by another service." >&2
  exit 1
fi

export HOST PORT
nohup "$PYTHON_BIN" "${SCRIPT_DIR}/server.py" >>"$STDOUT_FILE" 2>>"$STDERR_FILE" </dev/null &
LAUNCH_PID=$!

for ((attempt=0; attempt<40; attempt++)); do
  if health_ok; then
    "$PYTHON_BIN" - "${RUNTIME_DIR}/launch-settings.json" "$HOST" "$PORT" <<'SAVE'
import json, os, sys
from pathlib import Path
path = Path(sys.argv[1])
temporary = path.with_name(path.name + ".tmp")
temporary.write_text(json.dumps({"host": sys.argv[2], "port": int(sys.argv[3])}), encoding="utf-8")
os.replace(temporary, path)
SAVE
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
