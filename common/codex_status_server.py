#!/usr/bin/env python3
from __future__ import annotations

import hmac
import ipaddress
import json
import os
import shutil
import socket
import sys
import threading
import time
from datetime import datetime
from http.server import ThreadingHTTPServer
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASE_DIR = Path(
    os.environ.get("CODEX_STATUS_BASE_DIR", PROJECT_ROOT / "mac" / "codex_status_server" / ".runtime")
).resolve()
COMMON_DIR = PROJECT_ROOT / "common"
if str(COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(COMMON_DIR))

import service_monitor  # noqa: E402
import service_state  # noqa: E402
from codex_telemetry import CodexTelemetry  # noqa: E402
from notifications import NotificationManager  # noqa: E402
from peer_services import PeerServiceManager  # noqa: E402
from service_config import (  # noqa: E402
    read_env_bool as read_env_bool,
)
from service_config import (  # noqa: E402
    read_env_choice as read_env_choice,
)
from service_config import (  # noqa: E402
    read_env_float as read_env_float,
)
from service_config import (  # noqa: E402
    read_env_int as read_env_int,
)
from service_config import (  # noqa: E402
    read_env_interval as read_env_interval,
)
from service_config import (  # noqa: E402
    read_env_patterns as read_env_patterns,
)
from service_http import StatusHandler as StatusHandler  # noqa: E402
from service_metadata import RAINMETER_PROTOCOL_VERSION, SERVICE_NAME, SERVICE_VERSION  # noqa: E402
from service_runtime import (  # noqa: E402
    RotatingTextLog,
    SessionFileIndex,
    SingleFlightWorker,
    atomic_write_json,
)
from state_store import JsonObjectStore  # noqa: E402
from usage_client import query_account_usage, split_command  # noqa: E402
from usage_data import (  # noqa: E402
    epoch_value,
    extract_credits_label,
    format_age_label,
    format_reset_label,
    parse_timestamp,
    parse_usage_window,
    remaining_value,
    used_percent_value,
)


def load_private_settings() -> dict[str, object]:
    path = PROJECT_ROOT / "status-auth.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def resolve_expose_task_details(settings: dict[str, object], environ: dict[str, str]) -> bool:
    configured = settings.get("expose_task_details", True)
    default = "1" if configured is not False else "0"
    return environ.get("EXPOSE_TASK_DETAILS", default) == "1"


PRIVATE_SETTINGS = load_private_settings()
STATUS_FILE = BASE_DIR / "status.json"
USAGE_CACHE_FILE = BASE_DIR / "usage-cache.json"
LOG_FILE = BASE_DIR / "status-server.log"
PID_FILE = BASE_DIR / "status-server.pid"
HOST = os.environ.get("HOST", "127.0.0.1")
DEFAULT_STATUS_PORT = 8767
PORT = read_env_int("PORT", DEFAULT_STATUS_PORT, 1, 65535)
AUTO_MONITOR = read_env_bool("AUTO_MONITOR_CODEX", True)
CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
CODEX_SESSIONS_DIR = CODEX_HOME / "sessions"
SESSION_FILE_INDEX = SessionFileIndex(CODEX_SESSIONS_DIR)
SUCCESS_HOLD_SECONDS = read_env_int("SUCCESS_HOLD_SECONDS", 45, 0, 3600)
ERROR_HOLD_SECONDS = read_env_int("ERROR_HOLD_SECONDS", 90, 0, 3600)
MONITOR_INTERVAL_SECONDS = read_env_float("MONITOR_INTERVAL_SECONDS", 0.25, 0.05, 60.0)
SESSION_DISCOVERY_INTERVAL_SECONDS = read_env_float("SESSION_DISCOVERY_INTERVAL_SECONDS", 3.0, 0.5, 300.0)
RUNNING_STALE_SECONDS = read_env_int("RUNNING_STALE_SECONDS", 300, 5, 86400)
USAGE_STALE_SECONDS = read_env_int("USAGE_STALE_SECONDS", 900, 30, 86400)
USAGE_REFRESH_INTERVAL_SECONDS = read_env_interval("USAGE_REFRESH_INTERVAL_SECONDS", 900, 60, 86400)
USAGE_BUSY_REFRESH_SECONDS = read_env_interval("USAGE_BUSY_REFRESH_SECONDS", 120, 30, 86400)
ACCOUNT_QUERY_TIMEOUT_SECONDS = read_env_float("ACCOUNT_QUERY_TIMEOUT_SECONDS", 45.0, 1.0, 300.0)
LOG_MAX_BYTES = read_env_int("LOG_MAX_BYTES", 5 * 1024 * 1024, 1024, 1024 * 1024 * 1024)
LOG_BACKUP_COUNT = read_env_int("LOG_BACKUP_COUNT", 3, 0, 100)
GIT_CACHE_SECONDS = read_env_float("GIT_CACHE_SECONDS", 2.0, 0.0, 60.0)
GIT_TIMEOUT_SECONDS = read_env_float("GIT_TIMEOUT_SECONDS", 2.5, 0.1, 30.0)
GIT_FETCH_INTERVAL_SECONDS = read_env_float("GIT_FETCH_INTERVAL_SECONDS", 300.0, 0.0, 86400.0)
GIT_FETCH_TIMEOUT_SECONDS = read_env_float("GIT_FETCH_TIMEOUT_SECONDS", 15.0, 1.0, 120.0)
TASK_STATS_SCOPE = read_env_choice("TASK_STATS_SCOPE", "task", {"turn", "task", "service"})
GIT_STATS_EXCLUDE = read_env_patterns("GIT_STATS_EXCLUDE", ".DS_Store")
GIT_INCLUDE_MODE_ONLY = read_env_bool("GIT_INCLUDE_MODE_ONLY", False)
CODEX_COMMAND = os.environ.get("CODEX_COMMAND", "").strip()
STATUS_ACCESS_TOKEN = os.environ.get("STATUS_ACCESS_TOKEN", str(PRIVATE_SETTINGS.get("access_token") or ""))
ALLOW_CORS = read_env_bool("ALLOW_CORS", bool(PRIVATE_SETTINGS.get("allow_cors")))
EXPOSE_TASK_DETAILS = resolve_expose_task_details(PRIVATE_SETTINGS, os.environ)
NOTIFICATIONS_ENABLED = read_env_bool("NOTIFICATIONS_ENABLED", bool(PRIVATE_SETTINGS.get("notifications_enabled")))
NOTIFICATION_QUIET_HOURS = os.environ.get(
    "NOTIFICATION_QUIET_HOURS", str(PRIVATE_SETTINGS.get("notification_quiet_hours") or "")
).strip()
NOTIFIER = NotificationManager(
    enabled=NOTIFICATIONS_ENABLED,
    quiet_hours=NOTIFICATION_QUIET_HOURS,
    notify_waiting=read_env_bool("NOTIFY_WAITING", True),
    notify_success=read_env_bool("NOTIFY_SUCCESS", True),
    notify_error=read_env_bool("NOTIFY_ERROR", True),
)
TELEMETRY = CodexTelemetry(
    CODEX_HOME,
    git_cache_seconds=GIT_CACHE_SECONDS,
    git_timeout_seconds=GIT_TIMEOUT_SECONDS,
    git_fetch_interval_seconds=GIT_FETCH_INTERVAL_SECONDS,
    git_fetch_timeout_seconds=GIT_FETCH_TIMEOUT_SECONDS,
    task_stats_scope=TASK_STATS_SCOPE,
    git_exclude_patterns=GIT_STATS_EXCLUDE,
    include_mode_only=GIT_INCLUDE_MODE_ONLY,
    background_git_statistics=True,
    history_path=BASE_DIR / "task-history.sqlite3",
)

DEFAULT_STATUS = {
    "status": "idle",
    "message": "Codex 空闲",
    "updated_at": "1970-01-01T00:00:00+00:00",
    "running_since": 0.0,
    "last_elapsed_seconds": 0,
    "task_usage_start_primary": None,
    "task_usage_start_secondary": None,
    "task_usage_end_primary": None,
    "task_usage_end_secondary": None,
    "task_usage_label": "期间账户变化 --",
    "task_usage_primary_label": "",
    "task_usage_secondary_label": "",
}

DEFAULT_USAGE = {
    "available": False,
    "plan_type": "",
    "primary_remaining_percent": "",
    "primary_remaining_value": None,
    "primary_used_percent": None,
    "primary_resets_at": "",
    "primary_resets_at_epoch": None,
    "secondary_remaining_percent": "",
    "secondary_remaining_value": None,
    "secondary_used_percent": None,
    "secondary_resets_at": "",
    "secondary_resets_at_epoch": None,
    "updated_at": "",
    "cached_at": "",
    "source_session": "",
    "source": "",
    "sync_label": "等待 Codex 账户额度查询",
    "credits_available": False,
    "credits_label": "",
}


PEER_SERVICES = PeerServiceManager(BASE_DIR / "peer-services.json")
state_store = JsonObjectStore()
status_lock = threading.RLock()
usage_lock = threading.RLock()
health_lock = threading.RLock()
service_log = RotatingTextLog(LOG_FILE, max_bytes=LOG_MAX_BYTES, backups=LOG_BACKUP_COUNT)
monitor_health: dict[str, object] = {
    "initialized": False,
    "heartbeat_at": 0.0,
    "last_scan_at": 0.0,
    "last_error": "",
    "last_error_at": 0.0,
    "tracked_files": 0,
}
usage_query_health: dict[str, object] = {
    "last_success_at": 0.0,
    "last_error": "",
    "last_error_at": 0.0,
}


def write_log(message: str) -> None:
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    print(message, flush=True)
    try:
        service_log.write(line)
    except OSError as exc:
        print(f"status-server.log write failed: {exc}", flush=True)


def update_monitor_health(**changes: object) -> None:
    with health_lock:
        monitor_health.update(changes)


def effective_status(status_data: dict[str, object], task_data: dict[str, object]) -> dict[str, object]:
    """Keep the HTTP status code and displayed task stage on one authoritative snapshot."""

    with health_lock:
        monitor_initialized = bool(monitor_health["initialized"])
    if not AUTO_MONITOR or not monitor_initialized:
        return status_data

    task_status = str(task_data.get("status") or "idle")
    if task_status not in {"idle", "running", "waiting", "success", "error"}:
        task_status = "error"
    result = status_data.copy()
    result["status"] = task_status
    result["message"] = str(task_data.get("stage") or "Codex 空闲")
    if task_data.get("updated_at"):
        result["updated_at"] = task_data["updated_at"]
    return result


def service_health_snapshot(
    usage: dict[str, object] | None = None, task_data: dict[str, object] | None = None
) -> dict[str, object]:
    now = time.time()
    usage = usage or read_usage_cache()
    with health_lock:
        monitor = monitor_health.copy()
        account = usage_query_health.copy()
    telemetry = TELEMETRY.runtime_health()
    worker = usage_refresh_worker.snapshot()
    reasons: list[str] = []
    level = "ok"

    heartbeat_age = now - float(monitor.get("heartbeat_at") or 0)
    if AUTO_MONITOR:
        if not monitor.get("initialized"):
            level = "degraded"
            reasons.append("监控正在初始化")
        elif heartbeat_age > max(5.0, SESSION_DISCOVERY_INTERVAL_SECONDS * 2, MONITOR_INTERVAL_SECONDS * 10):
            level = "error"
            reasons.append("会话监控心跳超时")
        if not CODEX_SESSIONS_DIR.exists():
            level = "error"
            reasons.append("Codex 会话目录不存在")
        if monitor.get("last_error") and now - float(monitor.get("last_error_at") or 0) < 300:
            if level == "ok":
                level = "degraded"
            reasons.append("会话监控最近发生异常")

    if worker.get("last_error") or account.get("last_error"):
        if level == "ok":
            level = "degraded"
        reasons.append("额度查询最近失败")
    usage_timestamp = parse_timestamp(usage.get("updated_at"))
    if usage.get("available") and usage_timestamp and now - usage_timestamp > USAGE_STALE_SECONDS:
        if level == "ok":
            level = "degraded"
        reasons.append("额度缓存已滞后")
    if telemetry.get("git_last_error"):
        if level == "ok":
            level = "degraded"
        reasons.append("Git 统计最近失败")
    remote_status = str((task_data or {}).get("git_remote_status") or "")
    remote_error = str((task_data or {}).get("git_remote_error_label") or "")
    if remote_status in {"different", "unconfirmed"}:
        if level == "ok":
            level = "degraded"
        reasons.append(f"Git {remote_error or '云端未确认'}")
    data_errors = state_store.errors()
    if telemetry.get("history_last_error"):
        data_errors.append("任务历史保存失败，当前状态仍可查看")
    if data_errors:
        if level == "ok":
            level = "degraded"
        reasons.extend(data_errors)

    components = {
        "listener": {"status": "ok", "label": "接口可访问"},
        "monitor": {
            "status": "disabled"
            if not AUTO_MONITOR
            else (
                "error"
                if not CODEX_SESSIONS_DIR.exists()
                or heartbeat_age > max(5.0, SESSION_DISCOVERY_INTERVAL_SECONDS * 2, MONITOR_INTERVAL_SECONDS * 10)
                and monitor.get("initialized")
                else "ok"
                if monitor.get("initialized")
                else "pending"
            ),
            "label": "未启用自动监控"
            if not AUTO_MONITOR
            else "已监听会话"
            if monitor.get("initialized")
            else "正在初始化",
        },
        "usage": {
            "status": "refreshing"
            if worker.get("running")
            else "degraded"
            if account.get("last_error")
            or not usage.get("available")
            or usage_timestamp
            and now - usage_timestamp > USAGE_STALE_SECONDS
            else "ok",
            "label": "正在查询" if worker.get("running") else usage.get("sync_label", "等待额度"),
        },
        "git": {
            "status": "degraded"
            if remote_status in {"different", "unconfirmed"} or telemetry.get("git_last_error")
            else "pending"
            if remote_status == "checking"
            else "ok",
            "label": str((task_data or {}).get("git_state_label") or "等待项目"),
        },
        "version": {"status": "ok", "label": f"服务 {SERVICE_VERSION} / 协议 {RAINMETER_PROTOCOL_VERSION}"},
        "runtime_data": {
            "status": "degraded" if data_errors else "ok",
            "label": data_errors[0] if data_errors else "运行数据正常",
        },
    }

    label = "服务正常" if level == "ok" else f"服务{'异常' if level == 'error' else '降级'} · {reasons[0]}"
    return {
        "ok": level != "error",
        "service": SERVICE_NAME,
        "service_version": SERVICE_VERSION,
        "protocol_version": RAINMETER_PROTOCOL_VERSION,
        "status": level,
        "label": label,
        "reasons": reasons,
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "monitor": {
            **monitor,
            "heartbeat_age_seconds": max(0, int(heartbeat_age)) if monitor.get("heartbeat_at") else None,
        },
        "usage_worker": worker,
        "usage_query": account,
        "telemetry": telemetry,
        "components": components,
    }


def request_authorized(client_address: str, query: dict[str, list[str]], authorization: str) -> bool:
    """Keep local Rainmeter access simple while protecting LAN endpoints."""
    try:
        if ipaddress.ip_address(client_address).is_loopback:
            return True
    except ValueError:
        pass
    if not STATUS_ACCESS_TOKEN:
        return True
    supplied = query.get("token", [""])[0]
    if authorization.startswith("Bearer "):
        supplied = authorization[7:]
    return hmac.compare_digest(supplied, STATUS_ACCESS_TOKEN)


def is_approval_review_event(event: dict[str, object]) -> bool:
    payload = event.get("payload", {})
    if not isinstance(payload, dict):
        return False

    event_type = str(event.get("type", ""))
    payload_type = str(payload.get("type", ""))
    payload_text = json.dumps(payload, ensure_ascii=False)

    if event_type == "session_meta":
        source = payload.get("source", {})
        if isinstance(source, dict) and "guardian" in json.dumps(source.get("subagent", {}), ensure_ascii=False):
            return True

    review_prompt_markers = (
        "APPROVAL REQUEST",
        "Reviewed Codex session id",
        "Planned action JSON",
        "approval assessment",
    )
    if event_type == "response_item" and payload_type == "message" and str(payload.get("role", "")) == "user":
        return any(marker in payload_text for marker in review_prompt_markers)

    if event_type == "event_msg" and payload_type == "user_message":
        return any(marker in payload_text for marker in review_prompt_markers)

    review_answer_markers = ("risk_level", "user_authorization", "outcome", "rationale")
    if event_type == "response_item" and payload_type == "message" and str(payload.get("role", "")) == "assistant":
        return str(payload.get("phase", "")) == "final_answer" and all(
            marker in payload_text for marker in review_answer_markers
        )

    if event_type == "event_msg" and payload_type == "agent_message":
        return str(payload.get("phase", "")) == "final_answer" and all(
            marker in payload_text for marker in review_answer_markers
        )

    return False


def write_status(status: str, message: str) -> None:
    return service_state.write_status(sys.modules[__name__], status, message)


def read_status() -> dict[str, object]:
    return service_state.read_status(sys.modules[__name__])


def safe_number(value: object, default: float = 0.0) -> float:
    return service_state.safe_number(sys.modules[__name__], value, default)


def validate_status_data(data: dict[str, object]) -> dict[str, object]:
    return service_state.validate_status_data(sys.modules[__name__], data)


def clean_field(value: object) -> str:
    return str(value).replace("|", "/").replace("\r", " ").replace("\n", " ")


def format_elapsed_seconds(seconds: object) -> str:
    try:
        total = max(0, int(float(seconds)))
    except (TypeError, ValueError, OverflowError):
        total = 0
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def iter_recent_session_files(limit: int = 20) -> list[Path]:
    return SESSION_FILE_INDEX.recent(limit)


def format_sync_label(usage: dict[str, object]) -> str:
    if not usage.get("available"):
        return "等待 Codex 写入额度"

    timestamp = parse_timestamp(usage.get("updated_at"))
    if not timestamp:
        return "最近同步"

    updated = datetime.fromtimestamp(timestamp).astimezone()
    label_time = updated.strftime("%H:%M")
    age_seconds = time.time() - timestamp
    if usage.get("source") == "session_event":
        if age_seconds > USAGE_STALE_SECONDS:
            return f"日志快照滞后 {format_age_label(age_seconds)}"
        return f"日志快照 {label_time}"
    if age_seconds > USAGE_STALE_SECONDS:
        return f"可能滞后 {format_age_label(age_seconds)}"
    return f"更新 {label_time}"


def read_usage_cache() -> dict[str, object]:
    return service_state.read_usage_cache(sys.modules[__name__])


def validate_usage_data(data: dict[str, object]) -> dict[str, object]:
    return service_state.validate_usage_data(sys.modules[__name__], data)


def public_usage(usage: dict[str, object]) -> dict[str, object]:
    usage = usage.copy()
    usage.pop("source_session", None)
    return usage


def write_usage_cache(usage: dict[str, object]) -> dict[str, object]:
    return service_state.write_usage_cache(sys.modules[__name__], usage)


def usage_from_session_rate_limits(event: dict[str, object], path: Path) -> dict[str, object] | None:
    payload = event.get("payload", {})
    if event.get("type") != "event_msg" or not isinstance(payload, dict) or payload.get("type") != "token_count":
        return None
    rate_limits = payload.get("rate_limits")
    if not isinstance(rate_limits, dict):
        return None
    primary = rate_limits.get("primary")
    if not isinstance(primary, dict):
        return None
    primary_remaining = remaining_value(primary.get("used_percent"))
    if primary_remaining is None:
        return None
    secondary = rate_limits.get("secondary")
    secondary = secondary if isinstance(secondary, dict) else {}
    secondary_remaining = remaining_value(secondary.get("used_percent")) if secondary else None
    timestamp = parse_timestamp(event.get("timestamp")) or time.time()
    credits = rate_limits.get("credits")
    credits_label = (
        extract_credits_label(credits) if isinstance(credits, dict) and credits.get("has_credits") is True else ""
    )
    return {
        **DEFAULT_USAGE,
        "available": True,
        "plan_type": str(rate_limits.get("plan_type") or ""),
        "primary_remaining_percent": f"{primary_remaining}%",
        "primary_remaining_value": primary_remaining,
        "primary_used_percent": used_percent_value(primary.get("used_percent")),
        "primary_resets_at": format_reset_label(primary.get("resets_at")),
        "primary_resets_at_epoch": epoch_value(primary.get("resets_at")),
        "secondary_remaining_percent": f"{secondary_remaining}%" if secondary_remaining is not None else "",
        "secondary_remaining_value": secondary_remaining,
        "secondary_used_percent": used_percent_value(secondary.get("used_percent")),
        "secondary_resets_at": format_reset_label(secondary.get("resets_at")) if secondary else "",
        "secondary_resets_at_epoch": epoch_value(secondary.get("resets_at")),
        "updated_at": datetime.fromtimestamp(timestamp).astimezone().isoformat(timespec="seconds"),
        "source_session": str(path),
        "source": "session_event",
        **parse_usage_window(primary, "primary", session=True),
        **parse_usage_window(secondary, "secondary", session=True),
        "credits_available": bool(credits_label),
        "credits_label": credits_label,
    }


def consider_session_usage_fallback(event: dict[str, object], path: Path) -> dict[str, object] | None:
    fallback = usage_from_session_rate_limits(event, path)
    if fallback is None:
        return None
    with usage_lock:
        current = read_usage_cache()
        current_timestamp = parse_timestamp(current.get("updated_at"))
        fallback_timestamp = parse_timestamp(fallback.get("updated_at"))
        with health_lock:
            query_failed = bool(usage_query_health.get("last_error"))
        current_is_fresh_app_server = (
            current.get("available")
            and current.get("source") == "app_server"
            and current_timestamp
            and time.time() - current_timestamp <= USAGE_STALE_SECONDS
            and not query_failed
        )
        if current_is_fresh_app_server:
            return None
        if current.get("available") and current_timestamp >= fallback_timestamp:
            return None
        try:
            return write_usage_cache(fallback)
        except OSError:
            return None


def latest_session_usage_fallback() -> dict[str, object] | None:
    latest: tuple[float, dict[str, object], Path] | None = None
    for path in iter_recent_session_files():
        try:
            with path.open("rb") as handle:
                size = path.stat().st_size
                handle.seek(max(0, size - 2 * 1024 * 1024))
                lines = handle.read().decode("utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            usage = usage_from_session_rate_limits(event, path)
            if usage is None:
                continue
            timestamp = parse_timestamp(usage.get("updated_at"))
            if latest is None or timestamp > latest[0]:
                latest = (timestamp, event, path)
            break
    return consider_session_usage_fallback(latest[1], latest[2]) if latest else None


def rainmeter_value(value: object) -> str:
    if value is None:
        return "-1"
    return str(value)


def build_rainmeter_payload(
    status_data: dict[str, object], usage_data: dict[str, object], task_data: dict[str, object]
) -> str:
    status_codes = {"idle": "0", "running": "1", "waiting": "2", "success": "3", "error": "4"}
    other_projects = task_data.get("other_active_projects")
    if isinstance(other_projects, list) and other_projects:
        names = [str(value) for value in other_projects[:2] if value]
        remaining_count = max(0, int(task_data.get("other_active_count") or 0) - len(names))
        active_label = f"并行 {' · '.join(names)}"
        if remaining_count:
            active_label += f" +{remaining_count}"
    else:
        active_label = str(task_data.get("other_active_project") or "")
    model_label = " ".join(
        value for value in (str(task_data.get("model") or ""), str(task_data.get("reasoning_effort") or "")) if value
    )
    return "{code}|{message}|{updated_at}|{primary_remaining}|{primary_reset}|{secondary_remaining}|{secondary_reset}|{task_elapsed}|{primary_value}|{secondary_value}|{sync_label}|{task_usage_primary}|{task_usage_secondary}|{project}|{task_title}|{active_label}|{git_branch}|{git_change}|{git_state}|{token_label}|{context_label}|{health_label}|{credits_available}|{credits_label}|{model_label}|{git_cumulative}|{primary_window}|{secondary_window}".format(
        primary_window=clean_field(usage_data.get("primary_window_label") or "主窗口"),
        secondary_window=clean_field(usage_data.get("secondary_window_label") or "第二窗口"),
        code=status_codes.get(str(status_data.get("status", "error")), "4"),
        message=clean_field(
            task_data.get("stage")
            if str(task_data.get("status", "idle")) != "idle"
            else status_data.get("message") or ""
        ),
        updated_at=clean_field(status_data.get("updated_at") or ""),
        primary_remaining=clean_field(usage_data.get("primary_remaining_percent") or "--"),
        primary_reset=clean_field(usage_data.get("primary_resets_at") or "--"),
        secondary_remaining=clean_field(usage_data.get("secondary_remaining_percent") or "--"),
        secondary_reset=clean_field(usage_data.get("secondary_resets_at") or "--"),
        task_elapsed=clean_field(format_elapsed_seconds(task_data.get("elapsed_seconds", 0))),
        primary_value=clean_field(rainmeter_value(usage_data.get("primary_remaining_value"))),
        secondary_value=clean_field(rainmeter_value(usage_data.get("secondary_remaining_value"))),
        sync_label=clean_field(usage_data.get("sync_label") or ""),
        task_usage_primary=clean_field(status_data.get("task_usage_primary_label") or ""),
        task_usage_secondary=clean_field(status_data.get("task_usage_secondary_label") or ""),
        project=clean_field(task_data.get("project") or "等待任务"),
        task_title=clean_field(task_data.get("task_title") or "暂无活动任务"),
        active_label=clean_field(active_label),
        git_branch=clean_field(task_data.get("git_branch") or "--"),
        git_change=clean_field(
            task_data.get("git_task_label") or task_data.get("git_change_label") or "本次 0 项  +0  -0"
        ),
        git_state=clean_field(task_data.get("git_state_label") or ""),
        token_label=clean_field(task_data.get("token_label") or "本轮 -- tokens"),
        context_label=clean_field(task_data.get("context_label") or "上下文 --"),
        health_label=clean_field(task_data.get("health_label") or "服务正常"),
        credits_available="1" if usage_data.get("credits_available") else "0",
        credits_label=clean_field(usage_data.get("credits_label") or ""),
        model_label=clean_field(model_label),
        git_cumulative=clean_field(
            task_data.get("git_sync_label") or task_data.get("git_cumulative_label") or "待推送 --"
        ),
    )


def build_tasks_payload(task_data: dict[str, object], limit: int = 5) -> str:
    tasks = task_data.get("active_tasks")
    tasks = tasks if isinstance(tasks, list) else []
    fields = [str(len(tasks))]
    for index in range(limit):
        task = tasks[index] if index < len(tasks) and isinstance(tasks[index], dict) else {}
        fields.extend(
            (
                clean_field(task.get("project") or ""),
                clean_field(task.get("task_title") or ""),
                clean_field(task.get("stage") or ""),
                clean_field(format_elapsed_seconds(task.get("elapsed_seconds", 0))) if task else "",
            )
        )
    return "|".join(fields)


def resolve_codex_command() -> list[str]:
    if CODEX_COMMAND:
        return split_command(CODEX_COMMAND, windows=os.name == "nt")

    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            bundled_cli_dir = Path(local_app_data) / "OpenAI" / "Codex" / "bin"
            candidates = [path for path in bundled_cli_dir.glob("*/codex.exe") if path.is_file()]
            if candidates:
                return [str(max(candidates, key=lambda path: path.stat().st_mtime))]

    command_on_path = shutil.which("codex")
    if command_on_path:
        return [command_on_path]

    if sys.platform == "darwin":
        for candidate in (
            Path("/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex"),
            Path("/Applications/Codex.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex"),
            Path("/Applications/Codex.app/Contents/Resources/codex"),
        ):
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return [str(candidate)]

    raise RuntimeError(
        "Codex CLI was not found. Install/open Codex Desktop, add codex to PATH, "
        "or set CODEX_COMMAND to the full Codex executable path."
    )


def query_live_account_usage() -> dict[str, object]:
    return query_account_usage(
        resolve_codex_command(),
        ACCOUNT_QUERY_TIMEOUT_SECONDS,
        defaults=DEFAULT_USAGE,
        version=SERVICE_VERSION,
        log=write_log,
    )


def refresh_usage_cache_once() -> dict[str, object]:
    try:
        usage = write_usage_cache(query_live_account_usage())
    except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
        write_log(f"Codex live account usage query failed: {exc}")
        with health_lock:
            usage_query_health.update({"last_error": f"{type(exc).__name__}: {exc}", "last_error_at": time.time()})
        try:
            return latest_session_usage_fallback() or read_usage_cache()
        except OSError:
            return read_usage_cache()
    with health_lock:
        usage_query_health.update({"last_success_at": time.time(), "last_error": "", "last_error_at": 0.0})
    return usage


def format_usage_delta(delta: float | None) -> str:
    if delta is None:
        return ""
    delta = max(0.0, delta)
    if delta < 0.05:
        return ""
    text = f"{delta:.1f}".rstrip("0").rstrip(".")
    return f"-{text}%"


def format_task_usage_label(primary_delta: float | None, secondary_delta: float | None) -> str:
    if primary_delta is None and secondary_delta is None:
        return "期间账户变化 --"
    primary = format_usage_delta(primary_delta) or "--"
    secondary = format_usage_delta(secondary_delta) or "--"
    return f"期间账户变化 {primary} / {secondary}"


def update_task_usage_snapshot(usage: dict[str, object] | None) -> None:
    if not usage:
        return

    primary_used = usage.get("primary_used_percent")
    secondary_used = usage.get("secondary_used_percent")
    if primary_used is None and secondary_used is None:
        return

    with status_lock:
        status_data = read_status()
        status = str(status_data.get("status", "idle"))
        if status not in {"running", "waiting", "success"}:
            return

        deltas: dict[str, float | None] = {}
        for prefix, used in (("primary", primary_used), ("secondary", secondary_used)):
            start_key = f"task_usage_start_{prefix}"
            baseline_key = f"usage_baseline_{prefix}"
            # Account sources and window resets are not comparable baselines.
            identity = [
                usage.get("source"),
                usage.get(f"{prefix}_resets_at_epoch"),
                usage.get(f"{prefix}_window_minutes"),
            ]
            start = status_data.get(start_key)
            previous_used = status_data.get(f"task_usage_end_{prefix}")
            if used is None:
                deltas[prefix] = None
                continue
            reset = status_data.get(baseline_key) != identity or start is None
            reset = reset or (previous_used is not None and float(used) < float(previous_used))
            if reset:
                start = used
            status_data[start_key] = start
            status_data[baseline_key] = identity
            status_data[f"task_usage_end_{prefix}"] = used
            deltas[prefix] = float(used) - float(start)
        status_data["task_usage_label"] = format_task_usage_label(deltas["primary"], deltas["secondary"])
        status_data["task_usage_primary_label"] = format_usage_delta(deltas["primary"])
        status_data["task_usage_secondary_label"] = format_usage_delta(deltas["secondary"])
        try:
            atomic_write_json(STATUS_FILE, status_data)
        except OSError:
            state_store.write_failed(STATUS_FILE, "任务额度摘要保存失败，已保留最后可用快照")
            raise
        state_store.accept(STATUS_FILE, status_data)


def refresh_usage_and_task_snapshot() -> None:
    try:
        update_task_usage_snapshot(refresh_usage_cache_once())
    except OSError as exc:
        write_log(f"Codex usage snapshot update failed: {exc}")


usage_refresh_worker = SingleFlightWorker(refresh_usage_and_task_snapshot, name="codex-usage-refresh")


def codex_status_monitor() -> None:
    return service_monitor.run_monitor(sys.modules[__name__])


class StatusServer(ThreadingHTTPServer):
    daemon_threads = True
    # Do not allow a second listener to share the status port. Platform launchers also
    # checks /health, while this socket setting closes the startup race.
    allow_reuse_address = os.name != "nt"

    def server_bind(self) -> None:
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def write_pid_file() -> None:
    atomic_write_json(
        PID_FILE,
        {
            "pid": os.getpid(),
            "port": PORT,
            "base_dir": str(BASE_DIR),
            "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        },
    )


def remove_pid_file() -> None:
    try:
        data = json.loads(PID_FILE.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return
    if isinstance(data, dict) and data.get("pid") == os.getpid():
        PID_FILE.unlink(missing_ok=True)


def dashboard_snapshot() -> dict[str, object]:
    usage = public_usage(read_usage_cache())
    task = TELEMETRY.public_snapshot(expose_details=EXPOSE_TASK_DETAILS)
    status = effective_status(read_status(), task)
    health = service_health_snapshot(usage, task)
    return {
        "status": status,
        "usage": usage,
        "task": task,
        "health": health,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "usage_refresh": usage_refresh_worker.snapshot(),
    }


def api_dispatch(method: str, path: str, query: dict[str, list[str]], data: dict[str, object]) -> tuple[int, object]:
    def parameter(name: str, default: str = "") -> str:
        return query.get(name, [default])[0]

    if method == "GET":
        if path == "/api/snapshot":
            return 200, dashboard_snapshot()
        if path == "/api/tasks":
            return 200, TELEMETRY.public_snapshot(expose_details=EXPOSE_TASK_DETAILS)
        if path == "/api/history":
            if not EXPOSE_TASK_DETAILS:
                return 200, {"items": [], "total": 0, "limit": 50, "offset": 0}
            return 200, TELEMETRY.history_query(
                project=parameter("project"),
                status=parameter("status"),
                since=parameter("since"),
                until=parameter("until"),
                limit=int(parameter("limit", "50")),
                offset=int(parameter("offset", "0")),
            )
        if path == "/api/peers":
            snapshot = PEER_SERVICES.public_snapshot()
            if not EXPOSE_TASK_DETAILS:
                for item in snapshot.get("items", []):
                    item["snapshot"] = None
            return 200, snapshot
    if method == "POST":
        if path == "/api/usage/refresh":
            started = usage_refresh_worker.request()
            return 202, {"ok": True, "started": started, "worker": usage_refresh_worker.snapshot()}
        if path == "/api/tasks/control":
            action = str(data.get("action") or "")
            result = TELEMETRY.control_task(
                action, session_id=str(data.get("session_id") or ""), turn_id=str(data.get("turn_id") or "")
            )
            if not result.get("ok"):
                return 400, result
            snapshot = TELEMETRY.snapshot()
            write_status(str(snapshot["status"]), str(snapshot["stage"]))
            return 200, result
        if path == "/api/peers":
            return 200, PEER_SERVICES.control(
                str(data.get("action") or ""),
                name=str(data.get("name") or ""),
                url=str(data.get("url") or ""),
                token=str(data.get("token") or ""),
                peer_id=str(data.get("peer_id") or data.get("id") or ""),
            )
    return 404, {"error": "接口不存在"}


def main() -> int:
    if not STATUS_FILE.exists():
        atomic_write_json(STATUS_FILE, DEFAULT_STATUS)

    try:
        server = StatusServer((HOST, PORT), StatusHandler)
    except OSError as exc:
        write_log(f"Codex status server failed to start on {HOST}:{PORT}: {exc}")
        return 1

    write_log(f"Codex status server {SERVICE_VERSION} started on {HOST}:{PORT} (protocol {RAINMETER_PROTOCOL_VERSION})")
    try:
        write_pid_file()
    except OSError as exc:
        write_log(f"Codex status PID file write failed: {exc}")
    print(f"Codex status server: http://{HOST}:{PORT}/status")
    print(f"Local computer: http://127.0.0.1:{PORT}/status")
    if HOST in {"0.0.0.0", "::"}:
        print(f"Other computer: http://THIS-COMPUTER-IP:{PORT}/status")
    else:
        print("LAN access: set HOST=0.0.0.0 before starting the server")
    print(f"Status file: {STATUS_FILE}")
    print(f"Log file: {LOG_FILE}")
    print(f"Codex usage sessions: {CODEX_SESSIONS_DIR}")
    PEER_SERVICES.start()
    if AUTO_MONITOR:
        threading.Thread(target=codex_status_monitor, name="codex-status-monitor", daemon=True).start()
        print(f"Auto monitor: {CODEX_SESSIONS_DIR}")
    else:
        print("Auto monitor: disabled")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        write_log("Codex status server stopped")
        server.server_close()
        PEER_SERVICES.stop()
        remove_pid_file()

    return 0


StatusHandler.app = sys.modules[__name__]


if __name__ == "__main__":
    raise SystemExit(main())
