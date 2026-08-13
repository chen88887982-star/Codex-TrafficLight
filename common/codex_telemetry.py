from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable


TERMINAL_STATES = {"success", "error"}
ACTIVE_STATES = {"running", "waiting"}


def parse_timestamp(value: object) -> float:
    if value in (None, ""):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def compact_number(value: object) -> str:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return "--"
    if number >= 1_000_000:
        return f"{number / 1_000_000:.1f}M".rstrip("0").rstrip(".")
    if number >= 1_000:
        return f"{number / 1_000:.1f}K".rstrip("0").rstrip(".")
    return str(number)


def count_unified_diff(unified_diff: object) -> tuple[int, int]:
    added = 0
    deleted = 0
    for line in str(unified_diff or "").splitlines():
        if line.startswith(("+++", "---", "@@")):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            deleted += 1
    return added, deleted


def friendly_tool_stage(name: object) -> str:
    value = str(name or "").lower()
    if "apply_patch" in value or "patch" in value:
        return "正在修改代码"
    if any(marker in value for marker in ("exec", "terminal", "command", "shell")):
        return "正在运行命令"
    if "web" in value or "search" in value or "browser" in value:
        return "正在查询资料"
    if "image" in value:
        return "正在处理图像"
    if any(marker in value for marker in ("read", "view", "open")):
        return "正在读取内容"
    if any(marker in value for marker in ("agent", "collaboration", "thread")):
        return "正在协调任务"
    return "正在使用工具"


@dataclass
class SessionTask:
    path: Path
    session_id: str = ""
    turn_id: str = ""
    cwd: str = ""
    title: str = ""
    status: str = "idle"
    stage: str = "Codex 空闲"
    started_at: float = 0.0
    updated_at: float = 0.0
    completed_at: float = 0.0
    duration_seconds: int = 0
    model: str = ""
    reasoning_effort: str = ""
    context_window: int = 0
    last_tokens: int = 0
    total_tokens: int = 0
    cached_input_tokens: int = 0
    reasoning_tokens: int = 0
    git_sha: str = ""
    git_branch: str = ""
    git_origin_url: str = ""
    patch_files: set[str] = field(default_factory=set)
    patch_added: int = 0
    patch_deleted: int = 0
    ignored: bool = False

    @property
    def project(self) -> str:
        if not self.cwd:
            return "未识别项目"
        return Path(self.cwd).name or self.cwd


class CodexTelemetry:
    def __init__(self, codex_home: Path, *, git_cache_seconds: float = 2.0) -> None:
        self.codex_home = codex_home
        self.git_cache_seconds = git_cache_seconds
        self._tasks: dict[Path, SessionTask] = {}
        self._thread_cache: dict[str, dict[str, object]] = {}
        self._git_cache: dict[tuple[str, str], tuple[float, dict[str, object]]] = {}
        self._lock = threading.RLock()

    def task_for(self, path: Path) -> SessionTask:
        path = path.resolve()
        with self._lock:
            task = self._tasks.get(path)
            if task is None:
                task = SessionTask(path=path)
                match = re.search(r"([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})", path.name)
                if match:
                    task.session_id = match.group(1)
                self._tasks[path] = task
            return task

    def mark_ignored(self, path: Path) -> None:
        with self._lock:
            self.task_for(path).ignored = True

    def rebuild(self, paths: Iterable[Path], *, tail_bytes: int = 2 * 1024 * 1024) -> None:
        for path in paths:
            task = self.task_for(path)
            try:
                with path.open("rb") as fh:
                    head = fh.readline().decode("utf-8", errors="replace")
                    size = path.stat().st_size
                    fh.seek(max(0, size - tail_bytes))
                    tail = fh.read().decode("utf-8", errors="replace")
            except OSError:
                continue
            lines = [head] + tail.splitlines()
            for line in lines:
                try:
                    event = json.loads(line)
                except (TypeError, json.JSONDecodeError):
                    continue
                if isinstance(event, dict):
                    self.ingest(event, path, reconstructing=True)
            self._enrich_thread(task)

    def ingest(self, event: dict[str, object], path: Path, *, reconstructing: bool = False) -> str:
        task = self.task_for(path)
        if task.ignored:
            return ""
        event_type = str(event.get("type", ""))
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            payload = {}
        payload_type = str(payload.get("type", ""))
        event_at = parse_timestamp(event.get("timestamp")) or time.time()

        with self._lock:
            if event_type == "session_meta":
                task.session_id = str(payload.get("id") or task.session_id)
                task.cwd = str(payload.get("cwd") or task.cwd)
                source = payload.get("source", {})
                if isinstance(source, dict) and "guardian" in json.dumps(source, ensure_ascii=False):
                    task.ignored = True
                task.updated_at = max(task.updated_at, event_at)
                self._enrich_thread(task)
                return ""

            if event_type == "turn_context":
                task.cwd = str(payload.get("cwd") or task.cwd)
                task.model = str(payload.get("model") or task.model)
                if task.model == "codex-auto-review":
                    task.ignored = True
                    return ""
                collaboration = payload.get("collaboration_mode", {})
                if isinstance(collaboration, dict):
                    settings = collaboration.get("settings", {})
                    if isinstance(settings, dict):
                        task.reasoning_effort = str(settings.get("reasoning_effort") or task.reasoning_effort)
                task.updated_at = max(task.updated_at, event_at)
                return ""

            if event_type == "event_msg" and payload_type == "task_started":
                task.turn_id = str(payload.get("turn_id") or "")
                task.status = "running"
                task.stage = "正在处理任务"
                task.started_at = parse_timestamp(payload.get("started_at")) or event_at
                task.updated_at = event_at
                task.completed_at = 0.0
                task.duration_seconds = 0
                task.context_window = int(payload.get("model_context_window") or task.context_window or 0)
                task.last_tokens = 0
                task.patch_files.clear()
                task.patch_added = 0
                task.patch_deleted = 0
                self._enrich_thread(task, refresh=True)
                return "running"

            if event_type == "event_msg" and payload_type in {
                "approval_request",
                "permission_request",
                "user_input_requested",
            }:
                self._set_active(task, "waiting", "等待用户确认", event_at)
                return "waiting"

            if event_type == "event_msg" and payload_type == "task_complete":
                self._finish_task(task, payload, event_at, "success", "任务完成")
                return "success"

            if event_type == "event_msg" and payload_type == "turn_aborted":
                self._finish_task(task, payload, event_at, "error", "任务已中止")
                return "error"

            if event_type == "event_msg" and payload_type == "patch_apply_end":
                changes = payload.get("changes", {})
                if isinstance(changes, dict):
                    for filename, change in changes.items():
                        task.patch_files.add(str(filename))
                        if isinstance(change, dict):
                            added, deleted = count_unified_diff(change.get("unified_diff"))
                            task.patch_added += added
                            task.patch_deleted += deleted
                self._set_active(task, "running", "正在更新代码", event_at)
                self.invalidate_git(task.cwd)
                return "running"

            if event_type == "event_msg" and payload_type == "token_count":
                info = payload.get("info", {})
                if isinstance(info, dict):
                    self._apply_token_info(task, info)
                task.updated_at = max(task.updated_at, event_at)
                return ""

            if event_type == "event_msg" and payload_type == "agent_message":
                if str(payload.get("phase", "")) == "final_answer":
                    self._finish_task(task, payload, event_at, "success", "任务完成")
                    return "success"
                self._set_active(task, "running", "正在生成回复", event_at)
                return "running"

            if event_type == "response_item" and payload_type == "function_call":
                arguments = str(payload.get("arguments", ""))
                if "require_escalated" in arguments:
                    self._set_active(task, "waiting", "等待用户确认", event_at)
                    return "waiting"
                self._set_active(task, "running", friendly_tool_stage(payload.get("name")), event_at)
                return "running"

            if event_type == "response_item" and payload_type == "function_call_output":
                self._set_active(task, "running", "正在处理工具结果", event_at)
                self.invalidate_git(task.cwd)
                return "running"

            if event_type == "response_item" and payload_type in {"reasoning", "message"}:
                phase = str(payload.get("phase", ""))
                if phase == "final_answer" and str(payload.get("role", "")) == "assistant":
                    self._finish_task(task, payload, event_at, "success", "任务完成")
                    return "success"
                self._set_active(task, "running", "正在生成回复", event_at)
                return "running"

        return ""

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            visible = [task for task in self._tasks.values() if not task.ignored and task.session_id]
            active = [task for task in visible if task.status in ACTIVE_STATES]
            candidates = active or [task for task in visible if task.status in TERMINAL_STATES] or visible
            candidates.sort(key=lambda item: item.updated_at, reverse=True)
            task = candidates[0] if candidates else None
            if task is None:
                return self._empty_snapshot()
            self._enrich_thread(task)
            git = self._git_stats(task)
            elapsed = 0
            if task.status in ACTIVE_STATES and task.started_at:
                elapsed = max(0, int(time.time() - task.started_at))
            elif task.duration_seconds:
                elapsed = task.duration_seconds
            context_percent = 0
            if task.context_window and task.last_tokens:
                context_percent = min(100, round(task.last_tokens * 100 / task.context_window))
            event_age = max(0, int(time.time() - task.updated_at)) if task.updated_at else 0
            return {
                "session_id": task.session_id,
                "turn_id": task.turn_id,
                "status": task.status,
                "stage": task.stage,
                "project": task.project,
                "task_title": task.title or task.project,
                "active_count": len(active),
                "other_active_count": max(0, len(active) - 1),
                "elapsed_seconds": elapsed,
                "model": task.model,
                "reasoning_effort": task.reasoning_effort,
                "last_tokens": task.last_tokens,
                "total_tokens": task.total_tokens,
                "cached_input_tokens": task.cached_input_tokens,
                "reasoning_tokens": task.reasoning_tokens,
                "token_label": f"本轮 {compact_number(task.last_tokens)} tokens" if task.last_tokens else "本轮 -- tokens",
                "context_percent": context_percent,
                "context_label": f"上下文 {context_percent}%" if task.context_window else "上下文 --",
                "updated_at": datetime.fromtimestamp(task.updated_at).astimezone().isoformat(timespec="seconds") if task.updated_at else "",
                "event_age_seconds": event_age,
                "health_label": self._health_label(event_age, bool(active)),
                **git,
            }

    def public_snapshot(self, *, expose_details: bool = False) -> dict[str, object]:
        snapshot = self.snapshot()
        if expose_details:
            return snapshot
        return {
            **self._empty_snapshot(),
            "status": snapshot["status"],
            "stage": snapshot["stage"],
            "active_count": snapshot["active_count"],
            "other_active_count": snapshot["other_active_count"],
            "elapsed_seconds": snapshot["elapsed_seconds"],
            "updated_at": snapshot["updated_at"],
            "event_age_seconds": snapshot["event_age_seconds"],
            "health_label": snapshot["health_label"],
            "project": "Codex",
            "task_title": "隐私模式：任务详情未共享",
            "git_change_label": "配置令牌后显示变更",
            "git_state_label": "",
            "token_label": "本轮 -- tokens",
            "context_label": "上下文 --",
        }

    def expire_stale(self, stale_seconds: int) -> bool:
        expired = False
        cutoff = time.time() - max(1, stale_seconds)
        with self._lock:
            for task in self._tasks.values():
                if task.status in ACTIVE_STATES and task.updated_at and task.updated_at < cutoff:
                    task.status = "idle"
                    task.stage = "Codex 空闲"
                    expired = True
        return expired

    def invalidate_git(self, cwd: str) -> None:
        if not cwd:
            return
        with self._lock:
            for key in list(self._git_cache):
                if key[0] == cwd:
                    self._git_cache.pop(key, None)

    def _set_active(self, task: SessionTask, status: str, stage: str, event_at: float) -> None:
        if not task.started_at:
            task.started_at = event_at
        task.status = status
        task.stage = stage
        task.updated_at = max(task.updated_at, event_at)

    def _finish_task(self, task: SessionTask, payload: dict[str, object], event_at: float, status: str, stage: str) -> None:
        completed_at = parse_timestamp(payload.get("completed_at")) or event_at
        duration_ms = payload.get("duration_ms")
        try:
            duration = int(float(duration_ms) / 1000) if duration_ms is not None else 0
        except (TypeError, ValueError):
            duration = 0
        if not duration and task.started_at:
            duration = max(0, int(completed_at - task.started_at))
        task.status = status
        task.stage = stage
        task.completed_at = completed_at
        task.updated_at = max(task.updated_at, event_at)
        task.duration_seconds = duration
        self.invalidate_git(task.cwd)

    def _apply_token_info(self, task: SessionTask, info: dict[str, object]) -> None:
        last = info.get("last_token_usage", {})
        total = info.get("total_token_usage", {})
        if isinstance(last, dict):
            task.last_tokens = int(last.get("total_tokens") or task.last_tokens or 0)
            task.cached_input_tokens = int(last.get("cached_input_tokens") or 0)
            task.reasoning_tokens = int(last.get("reasoning_output_tokens") or 0)
        if isinstance(total, dict):
            task.total_tokens = int(total.get("total_tokens") or task.total_tokens or 0)
        task.context_window = int(info.get("model_context_window") or task.context_window or 0)

    def _enrich_thread(self, task: SessionTask, *, refresh: bool = False) -> None:
        if not task.session_id:
            return
        if refresh:
            self._thread_cache.pop(task.session_id, None)
        metadata = self._thread_cache.get(task.session_id)
        if metadata is None:
            metadata = self._read_thread_metadata(task.session_id)
            self._thread_cache[task.session_id] = metadata
        task.title = str(metadata.get("title") or task.title)
        task.cwd = str(metadata.get("cwd") or task.cwd)
        task.git_sha = str(metadata.get("git_sha") or task.git_sha)
        task.git_branch = str(metadata.get("git_branch") or task.git_branch)
        task.git_origin_url = str(metadata.get("git_origin_url") or task.git_origin_url)
        task.model = str(metadata.get("model") or task.model)
        task.reasoning_effort = str(metadata.get("reasoning_effort") or task.reasoning_effort)

    def _read_thread_metadata(self, session_id: str) -> dict[str, object]:
        candidates = [self.codex_home / "state_5.sqlite", self.codex_home / "sqlite" / "state_5.sqlite"]
        query = (
            "SELECT title, cwd, git_sha, git_branch, git_origin_url, model, reasoning_effort "
            "FROM threads WHERE id = ? LIMIT 1"
        )
        for database in candidates:
            if not database.exists():
                continue
            try:
                connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=0.5)
                try:
                    row = connection.execute(query, (session_id,)).fetchone()
                finally:
                    connection.close()
            except (OSError, sqlite3.Error):
                continue
            if row:
                keys = ("title", "cwd", "git_sha", "git_branch", "git_origin_url", "model", "reasoning_effort")
                return dict(zip(keys, row))
        return {}

    def _git_stats(self, task: SessionTask) -> dict[str, object]:
        empty = {
            "git_available": False,
            "git_branch": task.git_branch,
            "git_files": 0,
            "git_added": 0,
            "git_deleted": 0,
            "git_commits": 0,
            "git_ahead": 0,
            "git_behind": 0,
            "git_dirty": False,
            "git_change_label": "非 Git 项目",
            "git_state_label": "",
        }
        if not task.cwd or not Path(task.cwd).is_dir():
            return empty
        key = (task.cwd, task.git_sha)
        cached = self._git_cache.get(key)
        if cached and time.monotonic() - cached[0] < self.git_cache_seconds:
            return cached[1].copy()

        def git(*args: str) -> tuple[int, str]:
            try:
                result = subprocess.run(
                    ["git", "-c", "core.quotepath=false", *args],
                    cwd=task.cwd,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=2.5,
                    env={**os.environ, "LC_ALL": "C"},
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                return 1, ""
            return result.returncode, result.stdout.strip()

        return_code, root = git("rev-parse", "--show-toplevel")
        if return_code or not root:
            return empty
        _, branch = git("branch", "--show-current")
        baseline = task.git_sha or "HEAD"
        diff_code, numstat = git("diff", "--numstat", baseline, "--")
        name_code, names_text = git("diff", "--name-only", baseline, "--")
        _, porcelain = git("status", "--porcelain", "--untracked-files=all")
        files = {line for line in names_text.splitlines() if line} if name_code == 0 else set()
        added = 0
        deleted = 0
        if diff_code == 0:
            for line in numstat.splitlines():
                parts = line.split("\t", 2)
                if len(parts) < 3:
                    continue
                if parts[0].isdigit():
                    added += int(parts[0])
                if parts[1].isdigit():
                    deleted += int(parts[1])
                files.add(parts[2])
        dirty = bool(porcelain)
        for line in porcelain.splitlines():
            if line.startswith("?? "):
                relative = line[3:]
                files.add(relative)
                candidate = Path(task.cwd) / relative
                try:
                    content = candidate.read_bytes() if candidate.is_file() and candidate.stat().st_size <= 2 * 1024 * 1024 else b""
                except OSError:
                    content = b""
                if content and b"\0" not in content:
                    added += len(content.decode("utf-8", errors="replace").splitlines())

        _, commits_text = git("rev-list", "--count", f"{baseline}..HEAD")
        try:
            commits = int(commits_text or 0)
        except ValueError:
            commits = 0
        ahead = 0
        behind = 0
        upstream_code, counts = git("rev-list", "--left-right", "--count", "@{upstream}...HEAD")
        if upstream_code == 0:
            parts = counts.split()
            if len(parts) == 2 and all(part.isdigit() for part in parts):
                behind, ahead = map(int, parts)

        if files:
            change_label = f"{len(files)} 文件  +{added}  -{deleted}"
        else:
            change_label = "无代码变更"
        state_parts: list[str] = []
        if dirty:
            state_parts.append("未提交")
        elif commits:
            state_parts.append("已提交")
        else:
            state_parts.append("工作区干净")
        if ahead:
            state_parts.append(f"领先 {ahead}")
        if behind:
            state_parts.append(f"落后 {behind}")
        result = {
            "git_available": True,
            "git_branch": branch or task.git_branch or "--",
            "git_files": len(files),
            "git_added": added,
            "git_deleted": deleted,
            "git_commits": commits,
            "git_ahead": ahead,
            "git_behind": behind,
            "git_dirty": dirty,
            "git_change_label": change_label,
            "git_state_label": " · ".join(state_parts),
        }
        self._git_cache[key] = (time.monotonic(), result.copy())
        return result

    @staticmethod
    def _health_label(event_age: int, active: bool) -> str:
        if active and event_age > 300:
            return "任务事件可能停滞"
        if event_age < 10:
            return "服务正常 · 刚刚更新"
        if event_age < 60:
            return f"服务正常 · {event_age}秒前"
        return f"服务正常 · {event_age // 60}分钟前"

    @staticmethod
    def _empty_snapshot() -> dict[str, object]:
        return {
            "session_id": "",
            "turn_id": "",
            "status": "idle",
            "stage": "Codex 空闲",
            "project": "等待任务",
            "task_title": "暂无活动任务",
            "active_count": 0,
            "other_active_count": 0,
            "elapsed_seconds": 0,
            "model": "",
            "reasoning_effort": "",
            "last_tokens": 0,
            "total_tokens": 0,
            "cached_input_tokens": 0,
            "reasoning_tokens": 0,
            "token_label": "本轮 -- tokens",
            "context_percent": 0,
            "context_label": "上下文 --",
            "updated_at": "",
            "event_age_seconds": 0,
            "health_label": "服务正常 · 等待任务",
            "git_available": False,
            "git_branch": "--",
            "git_files": 0,
            "git_added": 0,
            "git_deleted": 0,
            "git_commits": 0,
            "git_ahead": 0,
            "git_behind": 0,
            "git_dirty": False,
            "git_change_label": "无代码变更",
            "git_state_label": "",
        }
