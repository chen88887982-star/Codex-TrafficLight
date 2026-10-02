"""Validated runtime status and usage persistence, independent of HTTP transport."""

from __future__ import annotations

import math
import time
from datetime import datetime
from types import ModuleType


def write_status(app: ModuleType, status: str, message: str) -> None:
    with app.status_lock:
        now = time.time()
        previous = app.read_status() if app.STATUS_FILE.exists() else app.DEFAULT_STATUS
        running_since = float(previous.get("running_since", 0) or 0)
        last_elapsed_seconds = int(float(previous.get("last_elapsed_seconds", 0) or 0))
        task_usage_start_primary = previous.get("task_usage_start_primary")
        task_usage_start_secondary = previous.get("task_usage_start_secondary")
        task_usage_end_primary = previous.get("task_usage_end_primary")
        task_usage_end_secondary = previous.get("task_usage_end_secondary")
        task_usage_label = str(previous.get("task_usage_label") or "期间账户变化 --")
        task_usage_primary_label = str(previous.get("task_usage_primary_label") or "")
        task_usage_secondary_label = str(previous.get("task_usage_secondary_label") or "")
        if status in {"running", "waiting"}:
            if previous.get("status") not in {"running", "waiting"} or running_since <= 0:
                previous = {key: value for key, value in previous.items() if not key.startswith("usage_baseline_")}
                running_since = now
                task_usage_start_primary = None
                task_usage_start_secondary = None
                task_usage_end_primary = None
                task_usage_end_secondary = None
                task_usage_label = "期间账户变化 --"
                task_usage_primary_label = ""
                task_usage_secondary_label = ""
        elif status == "success":
            if running_since > 0:
                last_elapsed_seconds = max(0, int(now - running_since))
            running_since = 0.0
        elif status in {"idle", "error"}:
            running_since = 0.0
            if status == "idle":
                last_elapsed_seconds = 0
        payload = {
            **{key: value for key, value in previous.items() if key.startswith("usage_baseline_")},
            "status": status,
            "message": message,
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "running_since": running_since,
            "last_elapsed_seconds": last_elapsed_seconds,
            "task_usage_start_primary": task_usage_start_primary,
            "task_usage_start_secondary": task_usage_start_secondary,
            "task_usage_end_primary": task_usage_end_primary,
            "task_usage_end_secondary": task_usage_end_secondary,
            "task_usage_label": task_usage_label,
            "task_usage_primary_label": task_usage_primary_label,
            "task_usage_secondary_label": task_usage_secondary_label,
        }
        try:
            app.atomic_write_json(app.STATUS_FILE, payload)
            app.state_store.accept(app.STATUS_FILE, payload)
        except OSError:
            app.state_store.write_failed(app.STATUS_FILE, "任务状态保存失败，已保留最后可用快照")
            raise


def read_status(app: ModuleType) -> dict[str, object]:
    with app.status_lock:
        data = app.state_store.read(app.STATUS_FILE, app.DEFAULT_STATUS, validate=app.validate_status_data)
    status = str(data.get("status", "idle"))
    if status not in {"idle", "running", "waiting", "success", "error"}:
        status = "error"
    return {
        **{key: value for key, value in data.items() if key.startswith("usage_baseline_")},
        "status": status,
        "message": str(data.get("message", "")),
        "updated_at": str(data.get("updated_at", "")),
        "running_since": data.get("running_since", 0) or 0,
        "last_elapsed_seconds": data.get("last_elapsed_seconds", 0) or 0,
        "task_usage_start_primary": data.get("task_usage_start_primary"),
        "task_usage_start_secondary": data.get("task_usage_start_secondary"),
        "task_usage_end_primary": data.get("task_usage_end_primary"),
        "task_usage_end_secondary": data.get("task_usage_end_secondary"),
        "task_usage_label": str(data.get("task_usage_label") or "期间账户变化 --"),
        "task_usage_primary_label": str(data.get("task_usage_primary_label") or ""),
        "task_usage_secondary_label": str(data.get("task_usage_secondary_label") or ""),
    }


def safe_number(app: ModuleType, value: object, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(0.0, number) if math.isfinite(number) else default


def validate_status_data(app: ModuleType, data: dict[str, object]) -> dict[str, object]:
    result = data.copy()
    result["running_since"] = app.safe_number(data.get("running_since"))
    result["last_elapsed_seconds"] = int(app.safe_number(data.get("last_elapsed_seconds")))
    for slot in ("start_primary", "start_secondary", "end_primary", "end_secondary"):
        result[f"task_usage_{slot}"] = app.used_percent_value(data.get(f"task_usage_{slot}"))
    return result


def read_usage_cache(app: ModuleType) -> dict[str, object]:
    with app.usage_lock:
        usage = app.state_store.read(app.USAGE_CACHE_FILE, app.DEFAULT_USAGE, validate=app.validate_usage_data)
        usage["sync_label"] = app.format_sync_label(usage)
        return usage


def validate_usage_data(app: ModuleType, data: dict[str, object]) -> dict[str, object]:
    if data.get("source") not in {"app_server", "session_event"}:
        raise ValueError("未知额度来源")
    result = {**app.DEFAULT_USAGE, **data}
    for prefix in ("primary", "secondary"):
        used = app.used_percent_value(data.get(f"{prefix}_used_percent"))
        remaining = app.used_percent_value(data.get(f"{prefix}_remaining_value"))
        if used is None and remaining is not None:
            used = app.used_percent_value(100 - remaining)
        window = {
            "usedPercent": used,
            "resetsAt": app.epoch_value(data.get(f"{prefix}_resets_at_epoch")),
            "windowDurationMins": app.epoch_value(data.get(f"{prefix}_window_minutes")),
        }
        result.update(app.parse_usage_window(window, prefix))
    result["available"] = result["primary_remaining_value"] is not None
    if data.get("available") and (not result["available"]):
        raise ValueError("主额度数值无效")
    result["credits_available"] = data.get("credits_available") is True
    result["credits_label"] = str(data.get("credits_label") or "")[:80]
    return result


def write_usage_cache(app: ModuleType, usage: dict[str, object]) -> dict[str, object]:
    with app.usage_lock:
        usage = usage.copy()
        usage["cached_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        usage["sync_label"] = app.format_sync_label(usage)
        try:
            app.atomic_write_json(app.USAGE_CACHE_FILE, usage)
            app.state_store.accept(app.USAGE_CACHE_FILE, usage)
        except OSError as exc:
            app.state_store.write_failed(app.USAGE_CACHE_FILE, "额度缓存保存失败，已保留最后可用快照")
            app.write_log(f"usage-cache.json write failed: {exc}")
            raise
        return usage
