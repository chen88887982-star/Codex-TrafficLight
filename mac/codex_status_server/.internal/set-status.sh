#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUNTIME_DIR="${SERVICE_DIR}/.runtime"
STATUS_FILE="${RUNTIME_DIR}/status.json"
mkdir -p "$RUNTIME_DIR"
STATUS="${1:-}"
MESSAGE="${2:-}"

case "$STATUS" in
  idle|running|waiting|success|error)
    ;;
  *)
    echo "Usage: $0 {idle|running|waiting|success|error} [message]" >&2
    exit 1
    ;;
esac

if [ -z "$MESSAGE" ]; then
  case "$STATUS" in
    idle) MESSAGE="Codex 空闲" ;;
    running) MESSAGE="Codex 正在执行任务" ;;
    waiting) MESSAGE="等待用户确认" ;;
    success) MESSAGE="任务完成" ;;
    error) MESSAGE="任务失败或异常" ;;
  esac
fi

python3 - "$STATUS_FILE" "$STATUS" "$MESSAGE" <<'PY'
import json
import sys
from datetime import datetime, timezone

path, status, message = sys.argv[1:4]
payload = {
    "status": status,
    "message": message,
    "updated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
}

with open(path, "w", encoding="utf-8") as fh:
    json.dump(payload, fh, ensure_ascii=False, indent=2)
    fh.write("\n")

print(json.dumps(payload, ensure_ascii=False))
PY
