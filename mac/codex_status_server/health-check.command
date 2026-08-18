#!/usr/bin/env bash
set -euo pipefail
PORT="${PORT:-8765}"
PAYLOAD="$(curl --silent --show-error --fail --max-time 3 "http://127.0.0.1:${PORT}/health")"
printf '%s' "$PAYLOAD" | python3 -m json.tool
printf '%s' "$PAYLOAD" | python3 -c 'import json,sys; d=json.load(sys.stdin); raise SystemExit(0 if d.get("service")=="codex-traffic-light-status" and d.get("status") != "error" else 1)'
