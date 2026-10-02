from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path


class RotatingTextLog:
    def __init__(self, path: Path, *, max_bytes: int = 5 * 1024 * 1024, backups: int = 3) -> None:
        self.path = path
        self.max_bytes = max(1024, max_bytes)
        self.backups = max(0, backups)
        self._lock = threading.Lock()
        self._normalize_backups()

    def write(self, line: str) -> None:
        encoded_size = len((line + "\n").encode("utf-8"))
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._rotate_if_needed(encoded_size)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    def _rotate_if_needed(self, incoming_size: int) -> None:
        try:
            current_size = self.path.stat().st_size
        except FileNotFoundError:
            return
        if current_size + incoming_size <= self.max_bytes:
            return

        if self.backups == 0:
            self.path.unlink(missing_ok=True)
            return

        oldest = self.path.with_name(f"{self.path.name}.{self.backups}")
        oldest.unlink(missing_ok=True)
        for index in range(self.backups - 1, 0, -1):
            source = self.path.with_name(f"{self.path.name}.{index}")
            destination = self.path.with_name(f"{self.path.name}.{index + 1}")
            if source.exists():
                os.replace(source, destination)
        os.replace(self.path, self.path.with_name(f"{self.path.name}.1"))

    def _normalize_backups(self) -> None:
        """Remove legacy backups that violate the configured retention contract."""

        prefix = f"{self.path.name}."
        try:
            candidates = list(self.path.parent.glob(f"{self.path.name}.*"))
        except OSError:
            return
        for candidate in candidates:
            suffix = candidate.name.removeprefix(prefix)
            if not suffix.isdigit():
                continue
            try:
                too_old = int(suffix) > self.backups
                too_large = candidate.stat().st_size > self.max_bytes
                if too_old or too_large or self.backups == 0:
                    candidate.unlink(missing_ok=True)
            except OSError:
                continue


def atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


class JsonlFollower:
    """Read only complete appended JSONL records and survive file replacement/truncation."""

    def __init__(self, *, max_read_bytes: int = 256 * 1024, max_line_bytes: int = 8 * 1024 * 1024) -> None:
        self.max_read_bytes = max(1024, max_read_bytes)
        self.max_line_bytes = max(1024, max_line_bytes)
        self._positions: dict[Path, int] = {}
        self._identities: dict[Path, tuple[int, int]] = {}
        self._pending: dict[Path, bytes] = {}
        self._pending_sizes: dict[Path, int] = {}

    def start_at_end(self, path: Path) -> None:
        stat = path.stat()
        self.start_at_offset(path, stat.st_size)

    def start_at_offset(self, path: Path, offset: int) -> None:
        stat = path.stat()
        self._positions[path] = max(0, min(int(offset), stat.st_size))
        self._identities[path] = (stat.st_dev, stat.st_ino)
        self._pending.pop(path, None)
        self._pending_sizes.pop(path, None)

    def read_lines(self, path: Path, *, stop_at: int | None = None) -> list[str]:
        try:
            with path.open("rb") as handle:
                stat = os.fstat(handle.fileno())
                identity = (stat.st_dev, stat.st_ino)
                position = self._positions.get(path, 0)
                if self._identities.get(path) not in (None, identity) or stat.st_size < position:
                    position = 0
                    self._pending.pop(path, None)
                    self._pending_sizes.pop(path, None)
                handle.seek(position)
                maximum = self.max_read_bytes
                if stop_at is not None:
                    maximum = min(maximum, max(0, stop_at - position))
                chunk = handle.read(maximum)
                self._positions[path] = handle.tell()
        except FileNotFoundError:
            self.forget(path)
            return []

        self._identities[path] = identity
        if not chunk:
            return []

        pending = self._pending.pop(path, b"")
        pending_size = self._pending_sizes.pop(path, 0)
        result = []
        for fragment in chunk.splitlines(keepends=True):
            pending_size += len(fragment)
            pending += fragment[: max(0, self.max_line_bytes - len(pending))]
            if fragment.endswith((b"\n", b"\r")):
                if pending_size <= self.max_line_bytes:
                    result.append(pending.rstrip(b"\r\n").decode("utf-8", errors="replace"))
                else:
                    summary = self._oversized_record(pending)
                    if summary:
                        result.append(summary)
                pending = b""
                pending_size = 0
        if pending_size:
            self._pending[path] = pending
            self._pending_sizes[path] = pending_size
        return result

    @staticmethod
    def _oversized_record(prefix: bytes) -> str:
        """Keep lifecycle fields from a large tool record without retaining its output."""
        text = prefix[: 64 * 1024].decode("utf-8", errors="replace")
        payload_start = re.search(r'"payload"\s*:\s*\{', text)
        if not payload_start:
            return ""
        head, payload = text[: payload_start.start()], text[payload_start.end() :]

        def string_field(source: str, field: str) -> str:
            match = re.search(r'"' + re.escape(field) + r'"\s*:\s*("(?:[^"\\]|\\.)*")', source)
            if not match:
                return ""
            try:
                return str(json.loads(match.group(1)))
            except json.JSONDecodeError:
                return ""

        event_type = string_field(head, "type")
        payload_type = string_field(payload, "type")
        if event_type not in {"event_msg", "response_item"} or not payload_type:
            return ""
        return json.dumps(
            {
                "type": event_type,
                "timestamp": string_field(head, "timestamp"),
                "payload": {key: string_field(payload, key) for key in ("type", "name", "role", "phase", "turn_id")},
                "_large_record_summary": True,
            }
        )

    def position_for(self, path: Path, *, complete_only: bool = False) -> int:
        position = self._positions.get(path, 0)
        return position - self._pending_sizes.get(path, 0) if complete_only else position

    def prune(self, active_paths: set[Path]) -> None:
        for path in set(self._positions) - active_paths:
            self.forget(path)

    def forget(self, path: Path) -> None:
        self._positions.pop(path, None)
        self._identities.pop(path, None)
        self._pending.pop(path, None)
        self._pending_sizes.pop(path, None)

    @property
    def tracked_count(self) -> int:
        return len(self._positions)

    @property
    def tracked_paths(self) -> set[Path]:
        return set(self._positions)


class SingleFlightWorker:
    """Run one background refresh at a time and coalesce overlapping requests."""

    def __init__(self, action: Callable[[], None], *, name: str) -> None:
        self._action = action
        self._name = name
        self._lock = threading.Lock()
        self._running = False
        self._pending = False
        self._last_started_at = 0.0
        self._last_finished_at = 0.0
        self._last_error = ""

    def request(self) -> bool:
        with self._lock:
            if self._running:
                self._pending = True
                return False
            self._running = True
            self._last_started_at = time.time()
        threading.Thread(target=self._run, name=self._name, daemon=True).start()
        return True

    def _run(self) -> None:
        try:
            while True:
                try:
                    self._action()
                except Exception as exc:
                    with self._lock:
                        self._last_error = f"{type(exc).__name__}: {exc}"
                else:
                    with self._lock:
                        self._last_error = ""
                finally:
                    with self._lock:
                        self._last_finished_at = time.time()
                with self._lock:
                    if self._pending:
                        self._pending = False
                        continue
                    self._running = False
                    return
        except BaseException:
            # Normal completion already clears _running under the same lock as
            # request(). A second unconditional clear could erase a new request.
            with self._lock:
                self._pending = False
                self._running = False
            raise

    @property
    def running(self) -> bool:
        with self._lock:
            return self._running

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "running": self._running,
                "pending": self._pending,
                "last_started_at": self._last_started_at,
                "last_finished_at": self._last_finished_at,
                "last_error": self._last_error,
            }


class IntervalScheduler:
    def __init__(self, interval_seconds: float, *, now: float | None = None) -> None:
        self.interval_seconds = max(0.0, interval_seconds)
        self.next_at = 0.0
        self.arm(now=now)

    def arm(self, *, now: float | None = None) -> None:
        current = time.monotonic() if now is None else now
        self.next_at = current + self.interval_seconds if self.interval_seconds else 0.0

    def due(self, *, now: float | None = None) -> bool:
        if not self.interval_seconds:
            return False
        current = time.monotonic() if now is None else now
        if current < self.next_at:
            return False
        self.next_at = current + self.interval_seconds
        return True


class TaskRefreshTracker:
    def __init__(self) -> None:
        self._pending: set[tuple[str, str]] = set()
        self._refreshed: set[tuple[str, str]] = set()

    def mark_active(self, task_key: tuple[str, str]) -> None:
        self._pending.add(task_key)

    def complete(self, task_key: tuple[str, str], *, success: bool) -> bool:
        # Both success and interruption can consume account usage.
        needs_refresh = task_key in self._pending and task_key not in self._refreshed
        self._pending.discard(task_key)
        if needs_refresh:
            self._refreshed.add(task_key)
        return needs_refresh

    def prune(self, active_paths: set[Path]) -> None:
        self._pending = {key for key in self._pending if Path(key[0]) in active_paths}
        self._refreshed = {key for key in self._refreshed if Path(key[0]) in active_paths}


class SessionFileIndex:
    """Scan recent date directories frequently; rediscover history at a bounded interval."""

    def __init__(self, root: Path, *, full_scan_seconds: float = 300) -> None:
        self.root = root
        self.full_scan_seconds = full_scan_seconds
        self._next_full_scan = 0.0
        self._known: set[Path] = set()
        self._lock = threading.Lock()

    def recent(self, limit: int = 20, *, now: float | None = None) -> list[Path]:
        now = time.monotonic() if now is None else now
        with self._lock:
            if now >= self._next_full_scan:
                candidates = set(self.root.rglob("rollout-*.jsonl"))
                self._next_full_scan = now + self.full_scan_seconds
            else:
                candidates = set(self._known)
                today = datetime.now()
                for offset in range(3):
                    directory = self.root / (today - timedelta(days=offset)).strftime("%Y/%m/%d")
                    candidates.update(directory.glob("rollout-*.jsonl"))
                candidates.update(self.root.glob("rollout-*.jsonl"))
            ranked = []
            for path in candidates:
                try:
                    ranked.append((path.stat().st_mtime, path))
                except FileNotFoundError:
                    continue
            ranked.sort(key=lambda item: (item[0], str(item[1])), reverse=True)
            # Active paths are independently retained by the monitor.
            self._known = {path for _, path in ranked[: max(limit, 100)]}
            return [path for _, path in ranked[:limit]]
