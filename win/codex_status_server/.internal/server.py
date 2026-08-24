#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SERVICE_DIR = SCRIPT_DIR.parent
BASE_DIR = SERVICE_DIR / ".runtime"
PROJECT_ROOT = SERVICE_DIR.parents[1]
COMMON_DIR = PROJECT_ROOT / "common"
BASE_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("CODEX_STATUS_BASE_DIR", str(BASE_DIR))
if str(COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(COMMON_DIR))

from codex_status_server import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
