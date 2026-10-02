from __future__ import annotations

import math
import os
import sys


def read_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name)
    try:
        value = int(raw) if raw is not None else default
    except ValueError:
        print(f"Invalid {name}={raw!r}; using {default}", file=sys.stderr)
        return default
    if not minimum <= value <= maximum:
        print(f"Out-of-range {name}={value}; using {default} ({minimum}..{maximum})", file=sys.stderr)
        return default
    return value


def read_env_interval(name: str, default: int, minimum_positive: int, maximum: int) -> int:
    raw = os.environ.get(name)
    try:
        value = int(raw) if raw is not None else default
    except ValueError:
        print(f"Invalid {name}={raw!r}; using {default}", file=sys.stderr)
        return default
    if value == 0 or minimum_positive <= value <= maximum:
        return value
    print(
        f"Out-of-range {name}={value}; using {default} (0 or {minimum_positive}..{maximum})",
        file=sys.stderr,
    )
    return default


def read_env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.environ.get(name)
    try:
        value = float(raw) if raw is not None else default
    except ValueError:
        print(f"Invalid {name}={raw!r}; using {default:g}", file=sys.stderr)
        return default
    if not math.isfinite(value) or not minimum <= value <= maximum:
        print(f"Out-of-range {name}={value}; using {default:g} ({minimum:g}..{maximum:g})", file=sys.stderr)
        return default
    return value


def read_env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    print(f"Invalid {name}={raw!r}; using {int(default)}", file=sys.stderr)
    return default


def read_env_choice(name: str, default: str, choices: set[str]) -> str:
    value = os.environ.get(name, default).strip().lower()
    if value in choices:
        return value
    print(f"Invalid {name}={value!r}; using {default}", file=sys.stderr)
    return default


def read_env_patterns(name: str, default: str) -> tuple[str, ...]:
    return tuple(pattern.strip() for pattern in os.environ.get(name, default).split(",") if pattern.strip())
