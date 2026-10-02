from __future__ import annotations

import csv
import io
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class TaskHistory:
    """Persist compact per-turn summaries, without prompts, repository paths or tool output."""

    FIELDS = (
        "session_id",
        "turn_id",
        "project",
        "task_title",
        "status",
        "started_at",
        "updated_at",
        "completed_at",
        "duration_seconds",
        "model",
        "reasoning_effort",
        "tokens",
        "last_tokens",
        "git_files",
        "git_added",
        "git_deleted",
        "git_commits",
        "git_ahead",
        "git_behind",
        "git_dirty",
    )
    INTEGER_FIELDS = set(FIELDS[8:9] + FIELDS[11:])
    REAL_FIELDS = {"started_at", "updated_at", "completed_at"}
    STATUSES = {"running", "waiting", "success", "error", "ignored", "idle"}

    def __init__(self, path: Path, *, retention_days: int = 90, max_records: int = 10000) -> None:
        self.path = Path(path)
        self.retention_days = max(1, retention_days)
        self.max_records = max(100, max_records)
        self._lock = threading.RLock()
        self._initialized = False
        self._next_cleanup = 0.0
        self._cleanup_timestamp = 0.0
        self._writes_since_cleanup = 0

    def _initialize(self, connection: sqlite3.Connection) -> None:
        columns = []
        for field in self.FIELDS:
            kind = "INTEGER" if field in self.INTEGER_FIELDS else "REAL" if field in self.REAL_FIELDS else "TEXT"
            columns.append(f"{field} {kind} NOT NULL")
        connection.execute(f"CREATE TABLE IF NOT EXISTS tasks ({','.join(columns)}, PRIMARY KEY(session_id, turn_id))")
        connection.execute("CREATE INDEX IF NOT EXISTS tasks_updated ON tasks(updated_at DESC)")
        connection.execute("CREATE INDEX IF NOT EXISTS tasks_project_status ON tasks(project, status, started_at)")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.path, timeout=5)
            if not self._initialized:
                try:
                    self._initialize(connection)
                except Exception:
                    connection.close()
                    raise
                self._initialized = True
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def record(self, summary: dict[str, object]) -> None:
        if not summary.get("session_id") or not summary.get("turn_id"):
            return
        values = []
        for field in self.FIELDS:
            value = summary.get(field)
            if field in self.INTEGER_FIELDS:
                value = int(value or 0)
            elif field in self.REAL_FIELDS:
                value = float(value or 0)
            else:
                value = str(value or "")
            values.append(value)
        updates = ",".join(f"{field}=excluded.{field}" for field in self.FIELDS[2:] if field in summary)
        placeholders = ",".join("?" for _ in self.FIELDS)
        with self._lock, self._connect() as connection:
            connection.execute(
                f"INSERT INTO tasks ({','.join(self.FIELDS)}) VALUES ({placeholders}) "
                f"ON CONFLICT(session_id,turn_id) DO UPDATE SET {updates}",
                values,
            )
            newest = float(summary.get("updated_at") or 0)
            self._writes_since_cleanup += 1
            now = time.monotonic()
            if (
                now >= self._next_cleanup
                or newest - self._cleanup_timestamp >= 3600
                or self._writes_since_cleanup >= 100
            ):
                cutoff = newest - self.retention_days * 86400
                connection.execute(
                    "DELETE FROM tasks WHERE updated_at < ? AND status NOT IN ('running','waiting')", (cutoff,)
                )
                connection.execute(
                    "DELETE FROM tasks WHERE rowid IN (SELECT rowid FROM tasks "
                    "WHERE status NOT IN ('running','waiting') ORDER BY updated_at DESC LIMIT -1 OFFSET ?)",
                    (self.max_records,),
                )
                self._next_cleanup = now + 300
                self._cleanup_timestamp = max(newest, self._cleanup_timestamp)
                self._writes_since_cleanup = 0

    def query(
        self,
        *,
        project: str = "",
        status: str = "",
        since: float = 0,
        until: float = 0,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, object]:
        limit = max(1, min(500, int(limit)))
        offset = max(0, int(offset))
        clauses = []
        params: list[object] = []
        for field, value in (("project", project), ("status", status)):
            if value:
                clauses.append(f"{field} = ?")
                params.append(value)
        if since:
            clauses.append("started_at >= ?")
            params.append(float(since))
        if until:
            clauses.append("started_at <= ?")
            params.append(float(until))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._lock, self._connect() as connection:
            total = connection.execute("SELECT count(*) FROM tasks" + where, params).fetchone()[0]
            rows = connection.execute(
                "SELECT * FROM tasks" + where + " ORDER BY started_at DESC, session_id, turn_id LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
        return {
            "available": True,
            "items": [dict(row) for row in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def export_csv(self, **filters: object) -> str:
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=self.FIELDS)
        writer.writeheader()
        offset = 0
        while True:
            result = self.query(**{**filters, "limit": 500, "offset": offset})
            rows = result["items"]
            for row in rows:
                safe = {
                    key: "'" + value
                    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@"))
                    else value
                    for key, value in row.items()
                }
                writer.writerow(safe)
            offset += len(rows)
            if offset >= result["total"] or not rows:
                break
        return output.getvalue()
