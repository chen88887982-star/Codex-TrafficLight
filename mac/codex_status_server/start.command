#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -f status.json ]; then
  ./set-status.sh idle
fi

export HOST="${HOST:-127.0.0.1}"
export CODEX_COMMAND="${CODEX_COMMAND:-/Applications/ChatGPT.app/Contents/Resources/codex}"
exec python3 server.py
