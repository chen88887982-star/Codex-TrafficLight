#!/usr/bin/env bash
set -euo pipefail

SERVICE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export HOST="${CODEX_STATUS_HOST:-}"
exec "${SERVICE_DIR}/.internal/start-background.command"
