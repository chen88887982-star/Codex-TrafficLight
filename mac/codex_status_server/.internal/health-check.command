#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SERVICE_DIR}/../.." && pwd)"
PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python3"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="$(command -v python3)"
fi
exec "$PYTHON_BIN" "${PROJECT_ROOT}/common/service_doctor.py" --service-dir "$SERVICE_DIR"
