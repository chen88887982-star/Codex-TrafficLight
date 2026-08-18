#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export HOST=0.0.0.0
exec "${SCRIPT_DIR}/start-background.command"
