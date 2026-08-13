#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parents[1]
COMMON_DIR = PROJECT_ROOT / "common"
os.environ.setdefault("CODEX_STATUS_BASE_DIR", str(BASE_DIR))
if str(COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(COMMON_DIR))

from codex_status_server import main


if __name__ == "__main__":
    raise SystemExit(main())
