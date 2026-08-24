from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path

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


def compact_task_title(value: object, limit: int = 72) -> str:
    title = " ".join(str(value or "").split())
    if not title:
        return ""
    return title if len(title) <= limit else f"{title[: limit - 1].rstrip()}…"


@dataclass
class SessionTask:
    path: Path
    session_id: str = ""
    turn_id: str = ""
    cwd: str = ""
    title: str = ""
    turn_title: str = ""
    pending_turn_title: str = ""
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
    turn_git_sha: str = ""
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
    def __init__(
        self,
        codex_home: Path,
        *,
        git_cache_seconds: float = 2.0,
        git_timeout_seconds: float = 2.5,
        git_fetch_interval_seconds: float = 0.0,
        git_fetch_timeout_seconds: float = 15.0,
        task_stats_scope: str = "task",
        git_exclude_patterns: Iterable[str] = (),
        include_mode_only: bool = False,
        background_git_statistics: bool = False,
    ) -> None:
        self.codex_home = codex_home
        self.git_cache_seconds = git_cache_seconds
        self.git_timeout_seconds = git_timeout_seconds
        self.git_fetch_interval_seconds = max(0.0, git_fetch_interval_seconds)
        self.git_fetch_timeout_seconds = max(0.1, git_fetch_timeout_seconds)
        self.task_stats_scope = task_stats_scope if task_stats_scope in {"turn", "task", "service"} else "task"
        self.git_exclude_patterns = tuple(pattern.strip() for pattern in git_exclude_patterns if pattern.strip())
        self.include_mode_only = include_mode_only
        self.background_git_statistics = background_git_statistics
        self._tasks: dict[Path, SessionTask] = {}
        self._thread_cache: dict[str, dict[str, object]] = {}
        self._git_cache: dict[tuple[str, str], tuple[float, dict[str, object]]] = {}
        self._service_git_baselines: dict[str, str] = {}
        self._git_refreshing: set[tuple[str, str]] = set()
        self._git_fetching: set[str] = set()
        self._git_fetch_last_attempt: dict[str, float] = {}
        self._git_fetch_last_success: dict[str, float] = {}
        self._git_fetch_errors: dict[str, str] = {}
        self._git_fetch_failures: dict[str, int] = {}
        self._git_fetch_next_attempt: dict[str, float] = {}
        self._git_remote_states: dict[str, dict[str, object]] = {}
        self._git_generations: dict[str, int] = {}
        self._git_last_finished_at = 0.0
        self._git_last_error = ""
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
            lines = tail.splitlines()
            if size > tail_bytes:
                lines.insert(0, head)
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

            if event_type == "event_msg" and payload_type == "user_message":
                title = compact_task_title(payload.get("message"))
                if title:
                    if task.status in ACTIVE_STATES:
                        task.turn_title = title
                    else:
                        task.pending_turn_title = title
                task.updated_at = max(task.updated_at, event_at)
                return ""

            if event_type == "event_msg" and payload_type == "task_started":
                task.turn_id = str(payload.get("turn_id") or "")
                task.turn_title = task.pending_turn_title
                task.pending_turn_title = ""
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
                if self.task_stats_scope == "turn" and not reconstructing:
                    task.turn_git_sha = self._git_head(task.cwd)
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

            if event_type == "event_msg" and payload_type == "agent_reasoning":
                self._set_active(task, "running", "正在分析任务", event_at)
                return "running"

            if event_type == "response_item" and payload_type in {"function_call", "custom_tool_call"}:
                arguments = str(payload.get("arguments") or payload.get("input") or "")
                if "require_escalated" in arguments:
                    self._set_active(task, "waiting", "等待用户确认", event_at)
                    return "waiting"
                self._set_active(task, "running", friendly_tool_stage(payload.get("name")), event_at)
                return "running"

            if event_type == "response_item" and payload_type in {"function_call_output", "custom_tool_call_output"}:
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
            other_active = [item for item in active if item is not task]
            other_active.sort(key=lambda item: item.updated_at, reverse=True)
            active_tasks = [self._task_summary(item) for item in active]
            other_active_projects = [item.project for item in other_active]
            self._enrich_thread(task)
            baseline = self._task_baseline(task)
            task_snapshot = replace(task, patch_files=set(task.patch_files))
            elapsed = 0
            if task.status in ACTIVE_STATES and task.started_at:
                elapsed = max(0, int(time.time() - task.started_at))
            elif task.duration_seconds:
                elapsed = task.duration_seconds
            context_percent = 0
            if task.context_window and task.last_tokens:
                context_percent = min(100, round(task.last_tokens * 100 / task.context_window))
            event_age = max(0, int(time.time() - task.updated_at)) if task.updated_at else 0
            snapshot = {
                "session_id": task.session_id,
                "turn_id": task.turn_id,
                "status": task.status,
                "stage": task.stage,
                "project": task.project,
                "task_title": task.turn_title or task.title or task.project,
                "active_count": len(active),
                "other_active_count": max(0, len(active) - 1),
                "other_active_project": other_active[0].project if other_active else "",
                "other_active_projects": other_active_projects,
                "active_tasks": active_tasks,
                "elapsed_seconds": elapsed,
                "model": task.model,
                "reasoning_effort": task.reasoning_effort,
                "last_tokens": task.last_tokens,
                "total_tokens": task.total_tokens,
                "cached_input_tokens": task.cached_input_tokens,
                "reasoning_tokens": task.reasoning_tokens,
                "token_label": f"本轮 {compact_number(task.last_tokens)} tokens"
                if task.last_tokens
                else "本轮 -- tokens",
                "context_percent": context_percent,
                "context_label": f"上下文 {context_percent}%" if task.context_window else "上下文 --",
                "updated_at": datetime.fromtimestamp(task.updated_at).astimezone().isoformat(timespec="seconds")
                if task.updated_at
                else "",
                "event_age_seconds": event_age,
                "health_label": self._health_label(event_age, bool(active)),
            }
        return {**snapshot, **self._git_snapshot(task_snapshot, baseline)}

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
            "other_active_project": "",
            "other_active_projects": [],
            "active_tasks": [],
            "elapsed_seconds": snapshot["elapsed_seconds"],
            "updated_at": snapshot["updated_at"],
            "event_age_seconds": snapshot["event_age_seconds"],
            "health_label": snapshot["health_label"],
            "project": "Codex",
            "task_title": "隐私模式：任务详情未共享",
            "git_task_label": "配置令牌后显示变更",
            "git_change_label": "配置令牌后显示变更",
            "git_state_label": "",
            "git_sync_label": "",
            "git_cumulative_label": "",
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

    def expire_completed(self, hold_seconds: int) -> bool:
        expired = False
        cutoff = time.time() - max(0, hold_seconds)
        with self._lock:
            for task in self._tasks.values():
                completed_at = task.completed_at or task.updated_at
                if task.status == "success" and completed_at and completed_at < cutoff:
                    task.status = "idle"
                    task.stage = "Codex 空闲"
                    expired = True
        return expired

    def active_paths(self) -> set[Path]:
        with self._lock:
            return {task.path for task in self._tasks.values() if task.status in ACTIVE_STATES and not task.ignored}

    def prune(self, active_paths: set[Path]) -> None:
        resolved = {path.resolve() for path in active_paths}
        with self._lock:
            removed = [path for path in self._tasks if path not in resolved]
            removed_sessions = {self._tasks[path].session_id for path in removed if self._tasks[path].session_id}
            for path in removed:
                self._tasks.pop(path, None)
            retained_sessions = {task.session_id for task in self._tasks.values() if task.session_id}
            for session_id in removed_sessions - retained_sessions:
                self._thread_cache.pop(session_id, None)
            retained_cwds = {task.cwd for task in self._tasks.values() if task.cwd}
            for key in list(self._git_cache):
                if key[0] not in retained_cwds:
                    self._git_cache.pop(key, None)
            for cwd in list(self._service_git_baselines):
                if cwd not in retained_cwds:
                    self._service_git_baselines.pop(cwd, None)
            for mapping in (
                self._git_fetch_last_attempt,
                self._git_fetch_last_success,
                self._git_fetch_errors,
                self._git_fetch_failures,
                self._git_fetch_next_attempt,
                self._git_remote_states,
            ):
                for cwd in list(mapping):
                    if cwd not in retained_cwds:
                        mapping.pop(cwd, None)
            self._git_fetching.intersection_update(retained_cwds)

    def runtime_health(self) -> dict[str, object]:
        with self._lock:
            last_fetch_error = list(self._git_fetch_errors.values())[-1] if self._git_fetch_errors else ""
            return {
                "tracked_tasks": len(self._tasks),
                "git_refreshing": len(self._git_refreshing),
                "git_last_finished_at": self._git_last_finished_at,
                "git_last_error": self._git_last_error,
                "git_fetching": len(self._git_fetching),
                "git_fetch_last_success": max(self._git_fetch_last_success.values(), default=0.0),
                "git_fetch_last_error": last_fetch_error,
                "git_fetch_unconfirmed": sum(
                    state.get("status") in {"different", "unconfirmed"} for state in self._git_remote_states.values()
                ),
            }

    def invalidate_git(self, cwd: str) -> None:
        if not cwd:
            return
        with self._lock:
            self._git_generations[cwd] = self._git_generations.get(cwd, 0) + 1
            for key in list(self._git_cache):
                if key[0] == cwd:
                    self._git_cache.pop(key, None)

    def _set_active(self, task: SessionTask, status: str, stage: str, event_at: float) -> None:
        if not task.started_at:
            task.started_at = event_at
        task.status = status
        task.stage = stage
        task.updated_at = max(task.updated_at, event_at)

    @staticmethod
    def _task_summary(task: SessionTask) -> dict[str, object]:
        elapsed = max(0, int(time.time() - task.started_at)) if task.started_at else 0
        return {
            "session_id": task.session_id,
            "turn_id": task.turn_id,
            "project": task.project,
            "task_title": task.turn_title or task.title or task.project,
            "status": task.status,
            "stage": task.stage,
            "elapsed_seconds": elapsed,
        }

    def _finish_task(
        self, task: SessionTask, payload: dict[str, object], event_at: float, status: str, stage: str
    ) -> None:
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

    def _git_head(self, cwd: str) -> str:
        if not cwd or not Path(cwd).is_dir():
            return ""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.git_timeout_seconds,
                env={**os.environ, "LC_ALL": "C"},
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        return result.stdout.strip() if result.returncode == 0 else ""

    def _task_baseline(self, task: SessionTask) -> str:
        if self.task_stats_scope == "turn":
            return task.turn_git_sha or task.git_sha or "HEAD"
        if self.task_stats_scope == "service":
            baseline = self._service_git_baselines.get(task.cwd)
            if baseline is None:
                baseline = self._git_head(task.cwd) or task.git_sha or "HEAD"
                self._service_git_baselines[task.cwd] = baseline
            return baseline
        return task.git_sha or "HEAD"

    def _git_path_excluded(self, relative: str) -> bool:
        normalized = relative.replace("\\", "/")
        basename = normalized.rsplit("/", 1)[-1]
        return any(fnmatch(normalized, pattern) or fnmatch(basename, pattern) for pattern in self.git_exclude_patterns)

    def _git_snapshot(self, task: SessionTask, baseline: str) -> dict[str, object]:
        if not self.background_git_statistics:
            return self._git_stats(task, baseline)

        key = (task.cwd, baseline)
        now = time.monotonic()
        with self._lock:
            cached = self._git_cache.get(key)
            fresh = cached and now - cached[0] < self.git_cache_seconds
            if not fresh and key not in self._git_refreshing:
                self._git_refreshing.add(key)
                generation = self._git_generations.get(task.cwd, 0)
                threading.Thread(
                    target=self._refresh_git_snapshot,
                    args=(task, baseline, key, generation),
                    name="codex-git-statistics",
                    daemon=True,
                ).start()
            if cached:
                return cached[1].copy()
        return self._empty_git_stats(task)

    def _refresh_git_snapshot(self, task: SessionTask, baseline: str, key: tuple[str, str], generation: int) -> None:
        try:
            self._refresh_git_tracking(task.cwd)
            result = self._git_stats(task, baseline, use_cache=False, cache_result=False)
        except Exception as exc:
            with self._lock:
                self._git_last_error = f"{type(exc).__name__}: {exc}"
        else:
            with self._lock:
                if self._git_generations.get(task.cwd, 0) == generation:
                    self._git_cache[key] = (time.monotonic(), result.copy())
                self._git_last_error = ""
                self._git_last_finished_at = time.time()
        finally:
            with self._lock:
                self._git_refreshing.discard(key)

    def _refresh_git_tracking(self, cwd: str) -> bool:
        """Refresh remote-tracking refs at a low frequency without blocking snapshots."""
        if not cwd or not self.git_fetch_interval_seconds or not Path(cwd).is_dir():
            return False
        now = time.monotonic()
        with self._lock:
            next_attempt = self._git_fetch_next_attempt.get(cwd, 0.0)
            if cwd in self._git_fetching or now < next_attempt:
                return False
            self._git_fetching.add(cwd)
            self._git_fetch_last_attempt[cwd] = now
        remote_name = ""
        merge_ref = ""
        try:
            branch = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.git_timeout_seconds,
                env={**os.environ, "LC_ALL": "C"},
                check=False,
            )
            branch_name = branch.stdout.strip() if branch.returncode == 0 else ""
            if not branch_name:
                return False
            remote = subprocess.run(
                ["git", "config", "--get", f"branch.{branch_name}.remote"],
                cwd=cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.git_timeout_seconds,
                env={**os.environ, "LC_ALL": "C"},
                check=False,
            )
            remote_name = remote.stdout.strip() if remote.returncode == 0 else ""
            if not remote_name or remote_name == ".":
                with self._lock:
                    self._git_remote_states[cwd] = {"status": "disabled", "error_label": ""}
                    self._git_fetch_next_attempt[cwd] = now + self.git_fetch_interval_seconds
                return False
            merge = subprocess.run(
                ["git", "config", "--get", f"branch.{branch_name}.merge"],
                cwd=cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.git_timeout_seconds,
                env={**os.environ, "LC_ALL": "C"},
                check=False,
            )
            merge_ref = merge.stdout.strip() if merge.returncode == 0 else f"refs/heads/{branch_name}"
            fetched = subprocess.run(
                ["git", "fetch", "--quiet", remote_name],
                cwd=cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.git_fetch_timeout_seconds,
                env={**os.environ, "LC_ALL": "C", "GIT_TERMINAL_PROMPT": "0"},
                check=False,
            )
            if fetched.returncode != 0:
                self._record_git_fetch_failure(
                    cwd,
                    now,
                    self._classify_git_error(fetched.stderr or fetched.stdout),
                    self._query_remote_tracking_state(cwd, remote_name, merge_ref),
                )
                return False
            with self._lock:
                self._git_fetch_last_success[cwd] = time.time()
                self._git_fetch_errors.pop(cwd, None)
                self._git_fetch_failures.pop(cwd, None)
                self._git_fetch_next_attempt[cwd] = now + self.git_fetch_interval_seconds
                self._git_remote_states[cwd] = {
                    "status": "verified",
                    "checked_at": time.time(),
                    "error_label": "",
                    "retry_seconds": int(self.git_fetch_interval_seconds),
                }
            return True
        except subprocess.TimeoutExpired:
            remote_state = (
                self._query_remote_tracking_state(cwd, remote_name, merge_ref)
                if remote_name and merge_ref
                else {"status": "unconfirmed"}
            )
            self._record_git_fetch_failure(cwd, now, "查询超时", remote_state)
            return False
        except OSError:
            remote_state = (
                self._query_remote_tracking_state(cwd, remote_name, merge_ref)
                if remote_name and merge_ref
                else {"status": "unconfirmed"}
            )
            self._record_git_fetch_failure(cwd, now, "Git 无法运行", remote_state)
            return False
        finally:
            with self._lock:
                self._git_fetching.discard(cwd)

    @staticmethod
    def _classify_git_error(message: str) -> str:
        value = message.lower()
        if any(marker in value for marker in ("authentication failed", "could not read username", "permission denied")):
            return "凭据失败"
        if any(
            marker in value for marker in ("cannot lock ref", "index.lock", "fetch_head.lock", "another git process")
        ):
            return "仓库锁冲突"
        if any(marker in value for marker in ("couldn't find remote ref", "remote ref does not exist")):
            return "远端分支不存在"
        if any(
            marker in value
            for marker in (
                "could not resolve",
                "could not connect",
                "failed to connect",
                "connection refused",
                "connection reset",
                "network is unreachable",
                "error sending request",
                "timed out",
                "rpc failed",
                "http/2",
                "tls",
            )
        ):
            return "网络失败"
        return "Git 刷新失败"

    @staticmethod
    def _git_retry_delay(failures: int) -> int:
        schedule = (15, 30, 60, 120, 300)
        return schedule[min(max(1, failures), len(schedule)) - 1]

    def _record_git_fetch_failure(
        self, cwd: str, attempted_at: float, error_label: str, remote_state: dict[str, object]
    ) -> None:
        with self._lock:
            failures = self._git_fetch_failures.get(cwd, 0) + 1
            retry_seconds = self._git_retry_delay(failures)
            status = str(remote_state.get("status") or "unconfirmed")
            state = {
                **remote_state,
                "status": status,
                "error_label": "" if status == "verified" else error_label,
                "retry_seconds": retry_seconds,
            }
            self._git_fetch_failures[cwd] = failures
            self._git_fetch_next_attempt[cwd] = attempted_at + retry_seconds
            self._git_remote_states[cwd] = state
            if status == "verified":
                self._git_fetch_errors.pop(cwd, None)
            else:
                self._git_fetch_errors[cwd] = error_label

    def _query_remote_tracking_state(self, cwd: str, remote_name: str, merge_ref: str) -> dict[str, object]:
        env = {**os.environ, "LC_ALL": "C", "GIT_TERMINAL_PROMPT": "0"}
        try:
            remote = subprocess.run(
                ["git", "ls-remote", "--heads", remote_name, merge_ref],
                cwd=cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.git_fetch_timeout_seconds,
                env=env,
                check=False,
            )
            upstream = subprocess.run(
                ["git", "rev-parse", "@{upstream}"],
                cwd=cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.git_timeout_seconds,
                env=env,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return {"status": "unconfirmed"}
        remote_head = remote.stdout.split(maxsplit=1)[0] if remote.returncode == 0 and remote.stdout.strip() else ""
        upstream_head = upstream.stdout.strip() if upstream.returncode == 0 else ""
        if not remote_head:
            return {"status": "unconfirmed"}
        return {
            "status": "verified" if remote_head == upstream_head else "different",
            "checked_at": time.time(),
        }

    @staticmethod
    def _empty_git_stats(task: SessionTask) -> dict[str, object]:
        empty = {
            "git_available": False,
            "git_branch": task.git_branch,
            "git_files": 0,
            "git_added": 0,
            "git_deleted": 0,
            "git_sync_files": 0,
            "git_sync_added": 0,
            "git_sync_deleted": 0,
            "git_commits": 0,
            "git_ahead": 0,
            "git_behind": 0,
            "git_dirty": False,
            "git_task_label": "本次 --",
            "git_change_label": "本次 --",
            "git_state_label": "",
            "git_remote_status": "disabled",
            "git_remote_error_label": "",
            "git_remote_retry_seconds": 0,
            "git_remote_checked_at": 0.0,
            "git_sync_label": "待推送 --",
            "git_cumulative_label": "待推送 --",
        }
        return empty

    def _git_stats(
        self,
        task: SessionTask,
        baseline: str | None = None,
        *,
        use_cache: bool = True,
        cache_result: bool = True,
    ) -> dict[str, object]:
        empty = self._empty_git_stats(task)
        if not task.cwd or not Path(task.cwd).is_dir():
            return empty
        baseline = baseline or self._task_baseline(task)
        key = (task.cwd, baseline)
        if use_cache:
            with self._lock:
                cached = self._git_cache.get(key)
                if cached and time.monotonic() - cached[0] < self.git_cache_seconds:
                    return cached[1].copy()

        def git(*args: str, strip: bool = True) -> tuple[int, str]:
            try:
                result = subprocess.run(
                    ["git", "-c", "core.quotepath=false", *args],
                    cwd=task.cwd,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self.git_timeout_seconds,
                    env={**os.environ, "LC_ALL": "C"},
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                return 1, ""
            return result.returncode, result.stdout.strip() if strip else result.stdout

        return_code, root = git("rev-parse", "--show-toplevel")
        if return_code or not root:
            return empty
        _, branch = git("branch", "--show-current")
        _, porcelain = git("status", "--porcelain=v1", "-z", "--untracked-files=all", strip=False)
        dirty = False
        untracked: dict[str, int] = {}
        records = porcelain.split("\0")
        index = 0
        while index < len(records):
            line = records[index]
            index += 1
            if not line:
                continue
            status_code = line[:2]
            relative = line[3:] if len(line) > 3 else ""
            if any(marker in status_code for marker in ("R", "C")) and index < len(records):
                index += 1
            if not relative or self._git_path_excluded(relative):
                continue
            dirty = True
            if status_code == "??":
                candidate = Path(task.cwd) / relative
                try:
                    content = (
                        candidate.read_bytes()
                        if candidate.is_file() and candidate.stat().st_size <= 2 * 1024 * 1024
                        else b""
                    )
                except OSError:
                    content = b""
                untracked[relative] = (
                    len(content.decode("utf-8", errors="replace").splitlines())
                    if content and b"\0" not in content
                    else 0
                )

        def diff_stats(reference: str) -> tuple[bool, set[str], int, int]:
            diff_code, numstat = git("diff", "--numstat", "-z", reference, "--", strip=False)
            name_code, names_text = git("diff", "--name-only", "-z", reference, "--", strip=False)
            files = (
                {line for line in names_text.split("\0") if line and not self._git_path_excluded(line)}
                if name_code == 0
                else set()
            )
            numstat_stats: dict[str, tuple[int | None, int | None]] = {}
            added = 0
            deleted = 0
            if diff_code == 0:
                records = numstat.split("\0")
                index = 0
                while index < len(records):
                    line = records[index]
                    index += 1
                    if not line:
                        continue
                    parts = line.split("\t", 2)
                    if len(parts) < 3:
                        continue
                    relative = parts[2]
                    if not relative and index + 1 < len(records):
                        index += 1
                        relative = records[index]
                        index += 1
                    if self._git_path_excluded(relative):
                        continue
                    file_added = int(parts[0]) if parts[0].isdigit() else None
                    file_deleted = int(parts[1]) if parts[1].isdigit() else None
                    numstat_stats[relative] = (file_added, file_deleted)
                    if parts[0].isdigit():
                        added += file_added or 0
                    if parts[1].isdigit():
                        deleted += file_deleted or 0
                    files.add(relative)
            summary_code, summary = git("diff", "--summary", reference, "--")
            if summary_code == 0:
                for line in summary.splitlines():
                    match = re.search(r"mode change \d+ => \d+ (.+)$", line)
                    if not match:
                        continue
                    relative = match.group(1)
                    stats = numstat_stats.get(relative)
                    if stats not in {None, (0, 0)}:
                        continue
                    if self.include_mode_only and not self._git_path_excluded(relative):
                        files.add(relative)
                    else:
                        files.discard(relative)
            for relative, line_count in untracked.items():
                files.add(relative)
                added += line_count
            return diff_code == 0 and name_code == 0, files, added, deleted

        _, task_files, task_added, task_deleted = diff_stats(baseline)

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

        if task_files:
            change_label = f"本次 {len(task_files)} 项  +{task_added}  -{task_deleted}"
        else:
            change_label = "本次 0 项  +0  -0"

        with self._lock:
            remote_state = self._git_remote_states.get(task.cwd, {}).copy()
            fetching = task.cwd in self._git_fetching
        remote_status = str(remote_state.get("status") or ("checking" if fetching else "disabled"))
        state_prefix = "云端" if remote_status == "verified" else "跟踪"
        if remote_status == "different":
            state_label = "云端 有更新"
        elif remote_status == "unconfirmed":
            state_label = "云端 未确认"
        elif remote_status == "checking":
            state_label = "云端 检查中"
        elif ahead and behind:
            state_label = f"{state_prefix} 分叉 +{ahead}/-{behind}"
        elif ahead:
            state_label = f"{state_prefix} 领先 {ahead}"
        elif behind:
            state_label = f"{state_prefix} 落后 {behind}"
        elif upstream_code == 0:
            state_label = f"{state_prefix} 已同步"
        else:
            state_label = "跟踪 未配置"

        if upstream_code == 0:
            _, sync_files, sync_added, sync_deleted = diff_stats("@{upstream}")
            cumulative_label = f"待推送 {len(sync_files)} 项  +{sync_added}  -{sync_deleted}"
        else:
            sync_files = set()
            sync_added = 0
            sync_deleted = 0
            cumulative_label = "待推送 --"
        result = {
            "git_available": True,
            "git_branch": branch or task.git_branch or "--",
            "git_files": len(task_files),
            "git_added": task_added,
            "git_deleted": task_deleted,
            "git_sync_files": len(sync_files),
            "git_sync_added": sync_added,
            "git_sync_deleted": sync_deleted,
            "git_commits": commits,
            "git_ahead": ahead,
            "git_behind": behind,
            "git_dirty": dirty,
            "git_task_label": change_label,
            "git_change_label": change_label,
            "git_state_label": state_label,
            "git_remote_status": remote_status,
            "git_remote_error_label": str(remote_state.get("error_label") or ""),
            "git_remote_retry_seconds": int(remote_state.get("retry_seconds") or 0),
            "git_remote_checked_at": float(remote_state.get("checked_at") or 0.0),
            "git_sync_label": cumulative_label,
            "git_cumulative_label": cumulative_label,
        }
        if cache_result:
            with self._lock:
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
            "other_active_project": "",
            "other_active_projects": [],
            "active_tasks": [],
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
            "git_task_label": "本次 0 项  +0  -0",
            "git_change_label": "本次 0 项  +0  -0",
            "git_state_label": "",
            "git_remote_status": "disabled",
            "git_remote_error_label": "",
            "git_remote_retry_seconds": 0,
            "git_remote_checked_at": 0.0,
            "git_sync_label": "待推送 --",
            "git_cumulative_label": "待推送 --",
        }
