#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SERVICE_DIR}/../.." && pwd)"
PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python3"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="$(command -v python3)"
fi
if [ -z "${PORT:-}" ]; then
  PORT="$("$PYTHON_BIN" - "${SERVICE_DIR}/.runtime/launch-settings.json" <<'SETTINGS'
import json, sys
from pathlib import Path
try:
    port = int(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["port"])
    if not 1 <= port <= 65535:
        raise ValueError
except (OSError, ValueError, KeyError, TypeError):
    port = 8767
print(port)
SETTINGS
)"
  export PORT
fi
exec "$PYTHON_BIN" "${PROJECT_ROOT}/common/service_doctor.py" --service-dir "$SERVICE_DIR"
