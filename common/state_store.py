"""Validate runtime JSON and retain the last complete in-process snapshot."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from pathlib import Path


def reject_json_constant(value: str) -> None:
    raise ValueError(f"JSON 不允许非有限数值: {value}")


class JsonObjectStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._snapshots: dict[Path, dict[str, object]] = {}
        self._errors: dict[Path, str] = {}
        self._write_errors: dict[Path, str] = {}

    def read(
        self,
        path: Path,
        defaults: dict[str, object],
        *,
        validate: Callable[[dict[str, object]], dict[str, object]] | None = None,
    ) -> dict[str, object]:
        with self._lock:
            try:
                with path.open("rb") as handle:
                    raw = handle.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    raise ValueError("运行数据过大")
                value = json.loads(raw.decode("utf-8-sig"), parse_constant=reject_json_constant)
                if not isinstance(value, dict):
                    raise ValueError("运行数据必须为 JSON 对象")
                result = {**defaults, **(validate(value) if validate else value)}
            except FileNotFoundError:
                return self._snapshots.get(path, defaults).copy()
            except (OSError, ValueError, TypeError, OverflowError):
                self._errors[path] = "运行数据无效，已保留最后可用快照"
                return self._snapshots.get(path, defaults).copy()
            self._errors.pop(path, None)
            self._snapshots[path] = result.copy()
            return result

    def accept(self, path: Path, value: dict[str, object]) -> None:
        with self._lock:
            self._snapshots[path] = value.copy()
            self._errors.pop(path, None)
            self._write_errors.pop(path, None)

    def write_failed(self, path: Path, message: str) -> None:
        with self._lock:
            self._write_errors[path] = message

    def errors(self) -> list[str]:
        with self._lock:
            return list(dict.fromkeys([*self._errors.values(), *self._write_errors.values()]))
