"""Log reconstruction and incremental task monitoring."""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import ModuleType

from service_runtime import IntervalScheduler, JsonlFollower, TaskRefreshTracker


def run_monitor(app: ModuleType) -> None:
    app.write_log(f"Codex auto monitor watching: {app.CODEX_SESSIONS_DIR}")
    follower = JsonlFollower()
    ignored_paths: set[Path] = set()
    last_success_at = 0.0
    refresh_tracker = TaskRefreshTracker()
    initialized = False
    monitor_started_at = time.time()
    usage_scheduler = IntervalScheduler(app.USAGE_REFRESH_INTERVAL_SECONDS)
    current_usage_interval = app.USAGE_REFRESH_INTERVAL_SECONDS
    files: list[Path] = []
    next_discovery_at = 0.0
    while True:
        app.update_monitor_health(heartbeat_at=time.time())
        try:
            monotonic_now = time.monotonic()
            target_interval = (
                min(app.USAGE_REFRESH_INTERVAL_SECONDS, app.USAGE_BUSY_REFRESH_SECONDS)
                if app.USAGE_REFRESH_INTERVAL_SECONDS
                and app.USAGE_BUSY_REFRESH_SECONDS
                and app.TELEMETRY.active_paths()
                else app.USAGE_REFRESH_INTERVAL_SECONDS
            )
            if target_interval != current_usage_interval:
                current_usage_interval = target_interval
                usage_scheduler.interval_seconds = target_interval
                usage_scheduler.arm(now=monotonic_now)
            if usage_scheduler.due(now=monotonic_now):
                app.usage_refresh_worker.request()
            if monotonic_now >= next_discovery_at:
                recent = app.iter_recent_session_files()
                retained_active = [path for path in app.TELEMETRY.active_paths() if path.exists()]
                files = list(dict.fromkeys([*recent, *retained_active]))
                next_discovery_at = monotonic_now + app.SESSION_DISCOVERY_INTERVAL_SECONDS
                app.update_monitor_health(last_scan_at=time.time(), tracked_files=len(files))
            if not files:
                app.update_monitor_health(initialized=True, tracked_files=0)
                if not initialized:
                    app.usage_refresh_worker.request()
                initialized = True
                time.sleep(min(1.0, app.SESSION_DISCOVERY_INTERVAL_SECONDS))
                continue
            if not initialized:
                offsets = app.TELEMETRY.rebuild(files)
                for path in files:
                    try:
                        follower.start_at_offset(path, offsets.get(path.resolve(), 0))
                    except FileNotFoundError:
                        continue
                    task = app.TELEMETRY.task_for(path)
                    if task.status in {"running", "waiting"}:
                        refresh_tracker.mark_active((str(path), task.turn_id or task.session_id))
                snapshot = app.TELEMETRY.snapshot()
                if snapshot["status"] in {"running", "waiting"}:
                    app.write_status(str(snapshot["status"]), str(snapshot["stage"]))
                    app.update_task_usage_snapshot(app.read_usage_cache())
                else:
                    app.write_status("idle", "Codex 空闲")
                app.usage_refresh_worker.request()
                initialized = True
                app.update_monitor_health(initialized=True)
                time.sleep(app.MONITOR_INTERVAL_SECONDS)
                continue
            for path in files:
                if path in ignored_paths:
                    continue
                if path not in follower.tracked_paths:
                    offsets = app.TELEMETRY.rebuild([path])
                    follower.start_at_offset(path, offsets.get(path.resolve(), 0))
                    task = app.TELEMETRY.task_for(path)
                    if task.ignored:
                        ignored_paths.add(path)
                        continue
                    if not task.dismissed and task.updated_at >= monitor_started_at:
                        task_key = (str(path), task.turn_id or task.session_id)
                        refresh_tracker.mark_active(task_key)
                        if task.status in {"success", "error"} and refresh_tracker.complete(
                            task_key, success=task.status == "success"
                        ):
                            app.usage_refresh_worker.request()
                        app.NOTIFIER.notify(task.status, task.turn_id or task.session_id, task.project)
                        snapshot = app.TELEMETRY.snapshot()
                        app.write_status(str(snapshot["status"]), str(snapshot["stage"]))
                        if task.status == "success":
                            last_success_at = time.time()
                for line in follower.read_lines(path):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(event, dict):
                        continue
                    try:
                        if app.is_approval_review_event(event):
                            ignored_paths.add(path)
                            app.TELEMETRY.mark_ignored(path)
                            app.write_log(f"Ignored approval review session: {path}")
                            break
                        fallback_usage = app.consider_session_usage_fallback(event, path)
                        if fallback_usage:
                            app.update_task_usage_snapshot(fallback_usage)
                        applied_status = app.TELEMETRY.ingest(event, path)
                        task = app.TELEMETRY.task_for(path)
                        if task.dismissed:
                            continue
                        task_key = (str(path), task.turn_id or task.session_id)
                        if applied_status in {"running", "waiting"}:
                            refresh_tracker.mark_active(task_key)
                            app.update_task_usage_snapshot(app.read_usage_cache())
                        elif applied_status in {"success", "error"}:
                            if refresh_tracker.complete(task_key, success=applied_status == "success"):
                                app.usage_refresh_worker.request()
                            if applied_status == "success":
                                last_success_at = time.time()
                        if applied_status:
                            app.NOTIFIER.notify(applied_status, task.turn_id or task.session_id, task.project)
                            snapshot = app.TELEMETRY.snapshot()
                            snapshot_status = str(snapshot["status"])
                            if snapshot_status in {"running", "waiting", "error"}:
                                app.write_status(snapshot_status, str(snapshot["stage"]))
                            elif snapshot_status == "success":
                                app.write_status("success", "Codex 任务完成")
                    except Exception as exc:
                        # The cursor already consumed this batch: isolate one bad record
                        # so subsequent task completion and quota events are retained.
                        app.write_log(f"Skipped invalid session record: {type(exc).__name__}")
                        app.update_monitor_health(
                            last_error=f"会话记录处理失败: {type(exc).__name__}",
                            last_error_at=time.time(),
                        )
            current = app.read_status()
            now = time.time()
            watched_paths = set(files)
            follower.prune(watched_paths)
            ignored_paths.intersection_update(watched_paths)
            refresh_tracker.prune(watched_paths)
            app.TELEMETRY.prune(watched_paths)
            app.update_monitor_health(tracked_files=follower.tracked_count)
            if (
                current.get("status") == "success"
                and last_success_at
                and (now - last_success_at > app.SUCCESS_HOLD_SECONDS)
            ):
                app.TELEMETRY.expire_completed(app.SUCCESS_HOLD_SECONDS)
                app.write_status("idle", "Codex 空闲")
                last_success_at = 0.0
            elif current.get("status") == "error" and app.TELEMETRY.expire_errors(app.ERROR_HOLD_SECONDS):
                app.write_status("idle", "Codex 空闲")
            elif app.TELEMETRY.expire_stale(app.RUNNING_STALE_SECONDS):
                snapshot = app.TELEMETRY.snapshot()
                app.write_status(str(snapshot["status"]), str(snapshot["stage"]))
        except Exception as exc:
            app.write_log(f"Codex auto monitor error: {exc}")
            app.update_monitor_health(last_error=f"{type(exc).__name__}: {exc}", last_error_at=time.time())
        time.sleep(app.MONITOR_INTERVAL_SECONDS)
