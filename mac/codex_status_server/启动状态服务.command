#!/usr/bin/env bash
set -euo pipefail

SERVICE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export HOST="${CODEX_STATUS_HOST:-0.0.0.0}"
exec "${SERVICE_DIR}/.internal/start-background.command"
