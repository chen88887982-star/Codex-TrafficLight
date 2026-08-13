#!/usr/bin/env python3
from __future__ import annotations

import json
import hmac
import math
import os
import queue
import shlex
import subprocess
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASE_DIR = Path(os.environ.get("CODEX_STATUS_BASE_DIR", PROJECT_ROOT / "mac" / "codex_status_server")).resolve()
COMMON_DIR = PROJECT_ROOT / "common"
if str(COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(COMMON_DIR))

from codex_telemetry import CodexTelemetry


def load_private_settings() -> dict[str, object]:
    path = PROJECT_ROOT / "status-auth.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


PRIVATE_SETTINGS = load_private_settings()
STATUS_FILE = BASE_DIR / "status.json"
USAGE_CACHE_FILE = BASE_DIR / "usage-cache.json"
LOG_FILE = BASE_DIR / "status-server.log"
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8765"))
AUTO_MONITOR = os.environ.get("AUTO_MONITOR_CODEX", "1") != "0"
CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
CODEX_SESSIONS_DIR = CODEX_HOME / "sessions"
SUCCESS_HOLD_SECONDS = int(os.environ.get("SUCCESS_HOLD_SECONDS", "45"))
MONITOR_INTERVAL_SECONDS = float(os.environ.get("MONITOR_INTERVAL_SECONDS", "0.25"))
RUNNING_STALE_SECONDS = int(os.environ.get("RUNNING_STALE_SECONDS", "300"))
USAGE_STALE_SECONDS = int(os.environ.get("USAGE_STALE_SECONDS", "900"))
ACCOUNT_QUERY_TIMEOUT_SECONDS = float(os.environ.get("ACCOUNT_QUERY_TIMEOUT_SECONDS", "45"))
CODEX_COMMAND = os.environ.get("CODEX_COMMAND", "codex")
STATUS_ACCESS_TOKEN = os.environ.get("STATUS_ACCESS_TOKEN", str(PRIVATE_SETTINGS.get("access_token") or ""))
ALLOW_CORS = os.environ.get("ALLOW_CORS", "1" if PRIVATE_SETTINGS.get("allow_cors") else "0") == "1"
EXPOSE_TASK_DETAILS = (
    os.environ.get("EXPOSE_TASK_DETAILS", "1" if PRIVATE_SETTINGS.get("expose_task_details") else "0") == "1"
    and bool(STATUS_ACCESS_TOKEN)
)
TELEMETRY = CodexTelemetry(CODEX_HOME)

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
    "task_usage_label": "本次 --",
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


status_lock = threading.Lock()
usage_lock = threading.RLock()


def write_log(message: str) -> None:
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    print(message, flush=True)
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


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
        return str(payload.get("phase", "")) == "final_answer" and all(marker in payload_text for marker in review_answer_markers)

    if event_type == "event_msg" and payload_type == "agent_message":
        return str(payload.get("phase", "")) == "final_answer" and all(marker in payload_text for marker in review_answer_markers)

    return False


def write_status(status: str, message: str) -> None:
    now = time.time()
    previous = read_status() if STATUS_FILE.exists() else DEFAULT_STATUS
    running_since = float(previous.get("running_since", 0) or 0)
    last_elapsed_seconds = int(float(previous.get("last_elapsed_seconds", 0) or 0))
    task_usage_start_primary = previous.get("task_usage_start_primary")
    task_usage_start_secondary = previous.get("task_usage_start_secondary")
    task_usage_end_primary = previous.get("task_usage_end_primary")
    task_usage_end_secondary = previous.get("task_usage_end_secondary")
    task_usage_label = str(previous.get("task_usage_label") or "本次 --")
    task_usage_primary_label = str(previous.get("task_usage_primary_label") or "")
    task_usage_secondary_label = str(previous.get("task_usage_secondary_label") or "")

    if status in {"running", "waiting"}:
        if previous.get("status") not in {"running", "waiting"} or running_since <= 0:
            running_since = now
            task_usage_start_primary = None
            task_usage_start_secondary = None
            task_usage_end_primary = None
            task_usage_end_secondary = None
            task_usage_label = "本次 --"
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
    with status_lock:
        STATUS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_status() -> dict[str, object]:
    if not STATUS_FILE.exists():
        return DEFAULT_STATUS

    try:
        with status_lock:
            data = json.loads(STATUS_FILE.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        write_log(f"status.json read failed: {exc}")
        return {
            "status": "error",
            "message": "status.json 读取失败",
            "updated_at": DEFAULT_STATUS["updated_at"],
        }

    status = str(data.get("status", "idle"))
    if status not in {"idle", "running", "waiting", "success", "error"}:
        status = "error"

    return {
        "status": status,
        "message": str(data.get("message", "")),
        "updated_at": str(data.get("updated_at", "")),
        "running_since": data.get("running_since", 0) or 0,
        "last_elapsed_seconds": data.get("last_elapsed_seconds", 0) or 0,
        "task_usage_start_primary": data.get("task_usage_start_primary"),
        "task_usage_start_secondary": data.get("task_usage_start_secondary"),
        "task_usage_end_primary": data.get("task_usage_end_primary"),
        "task_usage_end_secondary": data.get("task_usage_end_secondary"),
        "task_usage_label": str(data.get("task_usage_label") or "本次 --"),
        "task_usage_primary_label": str(data.get("task_usage_primary_label") or ""),
        "task_usage_secondary_label": str(data.get("task_usage_secondary_label") or ""),
    }


def clean_field(value: object) -> str:
    return str(value).replace("|", "/").replace("\r", " ").replace("\n", " ")


def format_elapsed_seconds(seconds: object) -> str:
    try:
        total = max(0, int(float(seconds)))
    except (TypeError, ValueError):
        total = 0
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def task_elapsed_label(status_data: dict[str, object]) -> str:
    status = str(status_data.get("status", "idle"))
    if status in {"running", "waiting"}:
        try:
            running_since = float(status_data.get("running_since", 0) or 0)
        except (TypeError, ValueError):
            running_since = 0.0
        if running_since > 0:
            return format_elapsed_seconds(time.time() - running_since)
        return "00:00"
    if status == "success":
        return "完成 " + format_elapsed_seconds(status_data.get("last_elapsed_seconds", 0))
    return "--:--"


def iter_recent_session_files(limit: int = 20) -> list[Path]:
    if not CODEX_SESSIONS_DIR.exists():
        return []
    files = list(CODEX_SESSIONS_DIR.rglob("rollout-*.jsonl"))
    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return files[:limit]


def format_reset_label(epoch_seconds: object, *, always_time: bool = False) -> str:
    try:
        reset_at = datetime.fromtimestamp(int(epoch_seconds)).astimezone()
    except (TypeError, ValueError, OSError):
        return "--"
    if always_time:
        return reset_at.strftime("%H:%M")
    now = datetime.now().astimezone()
    if reset_at.date() == now.date():
        return reset_at.strftime("%H:%M")
    return f"{reset_at.month}月{reset_at.day}日 {reset_at:%H:%M}"


def remaining_value(used_percent: object) -> int | None:
    try:
        remaining = 100 - float(used_percent)
    except (TypeError, ValueError):
        return None
    return max(0, min(100, math.floor(remaining)))


def remaining_percent(used_percent: object) -> str:
    remaining = remaining_value(used_percent)
    if remaining is None:
        return "--"
    return f"{remaining}%"


def used_percent_value(used_percent: object) -> float | None:
    try:
        used = float(used_percent)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(100.0, used))


def epoch_value(epoch_seconds: object) -> int | None:
    try:
        return int(epoch_seconds)
    except (TypeError, ValueError):
        return None


def parse_timestamp(value: object) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def format_age_label(seconds: float) -> str:
    seconds = max(0.0, seconds)
    if seconds < 60:
        return "刚刚"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes} 分钟"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} 小时"
    days = hours // 24
    return f"{days} 天"


def format_sync_label(usage: dict[str, object]) -> str:
    if not usage.get("available"):
        return "等待 Codex 写入额度"

    timestamp = parse_timestamp(usage.get("updated_at"))
    if not timestamp:
        return "最近同步"

    updated = datetime.fromtimestamp(timestamp).astimezone()
    label_time = updated.strftime("%H:%M")
    age_seconds = time.time() - timestamp
    if age_seconds > USAGE_STALE_SECONDS:
        return f"可能滞后 {format_age_label(age_seconds)}"
    return f"更新 {label_time}"


def read_usage_cache() -> dict[str, object]:
    with usage_lock:
        try:
            data = json.loads(USAGE_CACHE_FILE.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return DEFAULT_USAGE.copy()
        if data.get("source") != "app_server":
            return DEFAULT_USAGE.copy()
        usage = DEFAULT_USAGE.copy()
        usage.update(data)
        usage["sync_label"] = format_sync_label(usage)
        return usage


def public_usage(usage: dict[str, object]) -> dict[str, object]:
    usage = usage.copy()
    usage.pop("source_session", None)
    return usage


def write_usage_cache(usage: dict[str, object]) -> dict[str, object]:
    with usage_lock:
        usage = usage.copy()
        usage["cached_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        usage["sync_label"] = format_sync_label(usage)
        try:
            USAGE_CACHE_FILE.write_text(json.dumps(usage, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            write_log(f"usage-cache.json write failed: {exc}")
        return usage


def rainmeter_value(value: object) -> str:
    if value is None:
        return "-1"
    return str(value)


def build_rainmeter_payload(
    status_data: dict[str, object], usage_data: dict[str, object], task_data: dict[str, object]
) -> str:
    status_codes = {"idle": "0", "running": "1", "waiting": "2", "success": "3", "error": "4"}
    other_active = int(task_data.get("other_active_count") or 0)
    active_label = f"另有 {other_active} 个任务" if other_active else ""
    model_label = " ".join(
        value for value in (str(task_data.get("model") or ""), str(task_data.get("reasoning_effort") or "")) if value
    )
    return "{code}|{message}|{updated_at}|{primary_remaining}|{primary_reset}|{secondary_remaining}|{secondary_reset}|{task_elapsed}|{primary_value}|{secondary_value}|{sync_label}|{task_usage_primary}|{task_usage_secondary}|{project}|{task_title}|{active_label}|{git_branch}|{git_change}|{git_state}|{token_label}|{context_label}|{health_label}|{credits_available}|{credits_label}|{model_label}".format(
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
        task_usage_primary="",
        task_usage_secondary="",
        project=clean_field(task_data.get("project") or "等待任务"),
        task_title=clean_field(task_data.get("task_title") or "暂无活动任务"),
        active_label=clean_field(active_label),
        git_branch=clean_field(task_data.get("git_branch") or "--"),
        git_change=clean_field(task_data.get("git_change_label") or "无代码变更"),
        git_state=clean_field(task_data.get("git_state_label") or ""),
        token_label=clean_field(task_data.get("token_label") or "本轮 -- tokens"),
        context_label=clean_field(task_data.get("context_label") or "上下文 --"),
        health_label=clean_field(task_data.get("health_label") or "服务正常"),
        credits_available="1" if usage_data.get("credits_available") else "0",
        credits_label=clean_field(usage_data.get("credits_label") or ""),
        model_label=clean_field(model_label),
    )


def remaining_percent_from_value(value: object) -> str:
    if value is None:
        return "--"
    return f"{value}%"


def extract_credits_label(usage: dict[str, object]) -> str:
    """Read an optional credits balance without assuming a fixed experimental schema."""

    keys = ("creditsBalance", "creditBalance", "remainingCredits", "balance")
    pending: list[object] = [usage]
    while pending:
        current = pending.pop()
        if not isinstance(current, dict):
            continue
        for key in keys:
            value = current.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return f"{value:g}"
            if isinstance(value, str) and value.strip():
                return value.strip()
        credits = current.get("credits")
        if isinstance(credits, dict):
            pending.append(credits)
        for value in current.values():
            if isinstance(value, dict) and value is not credits:
                pending.append(value)
    return ""


def same_reset_cycle(usage: dict[str, object], cached: dict[str, object], prefix: str) -> bool:
    usage_epoch = usage.get(f"{prefix}_resets_at_epoch")
    cached_epoch = cached.get(f"{prefix}_resets_at_epoch")
    if usage_epoch is not None and cached_epoch is not None:
        return usage_epoch == cached_epoch
    return usage.get(f"{prefix}_resets_at") == cached.get(f"{prefix}_resets_at")


def apply_conservative_usage_floor(usage: dict[str, object], cached: dict[str, object]) -> dict[str, object]:
    if not cached.get("available"):
        return usage

    usage = usage.copy()
    for prefix in ("primary", "secondary"):
        if not same_reset_cycle(usage, cached, prefix):
            continue

        usage_remaining = usage.get(f"{prefix}_remaining_value")
        cached_remaining = cached.get(f"{prefix}_remaining_value")
        if isinstance(usage_remaining, int) and isinstance(cached_remaining, int):
            remaining = min(usage_remaining, cached_remaining)
            usage[f"{prefix}_remaining_value"] = remaining
            usage[f"{prefix}_remaining_percent"] = remaining_percent_from_value(remaining)

        usage_used = usage.get(f"{prefix}_used_percent")
        cached_used = cached.get(f"{prefix}_used_percent")
        if isinstance(usage_used, (int, float)) and isinstance(cached_used, (int, float)):
            usage[f"{prefix}_used_percent"] = max(float(usage_used), float(cached_used))

    return usage


def usage_cache_needs_update(usage: dict[str, object], cached: dict[str, object]) -> bool:
    if not cached.get("available"):
        return True

    usage_timestamp = parse_timestamp(usage.get("updated_at"))
    cached_timestamp = parse_timestamp(cached.get("updated_at"))
    if usage_timestamp < cached_timestamp:
        return False
    if usage_timestamp > cached_timestamp:
        return True

    fields = (
        "updated_at",
        "source_session",
        "primary_used_percent",
        "primary_resets_at_epoch",
        "secondary_used_percent",
        "secondary_resets_at_epoch",
        "primary_remaining_value",
        "secondary_remaining_value",
    )
    return any(usage.get(field) != cached.get(field) for field in fields)


def maybe_update_usage_cache(usage: dict[str, object] | None) -> dict[str, object]:
    return read_usage_cache()


def query_live_account_usage() -> dict[str, object]:
    process = subprocess.Popen(shlex.split(CODEX_COMMAND) + ["app-server", "--stdio"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", bufsize=1)
    messages: queue.Queue[dict[str, object]] = queue.Queue()
    def reader() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            try:
                item = json.loads(line)
                if isinstance(item, dict): messages.put(item)
            except json.JSONDecodeError: pass
    threading.Thread(target=reader, daemon=True).start()
    def request(request_id: int, method: str, params: object) -> dict[str, object]:
        assert process.stdin is not None
        process.stdin.write(json.dumps({"id": request_id, "method": method, "params": params}) + "\n"); process.stdin.flush()
        deadline = time.monotonic() + ACCOUNT_QUERY_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            try: item = messages.get(timeout=0.25)
            except queue.Empty: continue
            if item.get("id") == request_id:
                result = item.get("result")
                if isinstance(result, dict): return result
                raise RuntimeError(str(item.get("error") or "Codex account query failed"))
        raise TimeoutError("Codex account query timed out")
    try:
        request(1, "initialize", {"clientInfo": {"name": "Codex-TrafficLight", "version": "1.0"}})
        limits = request(2, "account/rateLimits/read", None)
        account_usage = request(3, "account/usage/read", None)
    finally:
        process.terminate()
    snapshots = limits.get("rateLimitsByLimitId")
    snapshot = snapshots.get("codex") if isinstance(snapshots, dict) else limits.get("rateLimits")
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("primary"), dict): raise RuntimeError("Codex returned no primary rate limit")
    primary = snapshot["primary"]
    remaining = remaining_value(primary.get("usedPercent"))
    credits_label = extract_credits_label(account_usage)
    return {
        **DEFAULT_USAGE,
        "available": remaining is not None,
        "plan_type": str(snapshot.get("planType") or ""),
        "primary_remaining_percent": f"{remaining}%" if remaining is not None else "--",
        "primary_remaining_value": remaining,
        "primary_used_percent": used_percent_value(primary.get("usedPercent")),
        "primary_resets_at": format_reset_label(primary.get("resetsAt")),
        "primary_resets_at_epoch": epoch_value(primary.get("resetsAt")),
        "secondary_remaining_percent": "",
        "secondary_resets_at": "",
        "credits_available": bool(credits_label),
        "credits_label": credits_label,
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": "app_server",
    }


def newer_usage(left: dict[str, object] | None, right: dict[str, object] | None) -> dict[str, object] | None:
    if left is None:
        return right
    if right is None:
        return left

    left_timestamp = parse_timestamp(left.get("updated_at"))
    right_timestamp = parse_timestamp(right.get("updated_at"))
    if right_timestamp > left_timestamp:
        return right
    return left


def usage_from_event(event: dict[str, object], source_session: Path | None = None) -> dict[str, object] | None:
    rate_limits = event.get("rate_limits")
    payload = event.get("payload")
    if rate_limits is None and isinstance(payload, dict):
        rate_limits = payload.get("rate_limits")
    if not isinstance(rate_limits, dict):
        return None
    primary = rate_limits.get("primary")
    secondary = rate_limits.get("secondary")
    if not isinstance(primary, dict) or not isinstance(secondary, dict):
        return None
    primary_remaining = remaining_value(primary.get("used_percent"))
    secondary_remaining = remaining_value(secondary.get("used_percent"))
    primary_used = used_percent_value(primary.get("used_percent"))
    secondary_used = used_percent_value(secondary.get("used_percent"))
    primary_resets_at = primary.get("resets_at")
    secondary_resets_at = secondary.get("resets_at")

    return {
        "available": True,
        "plan_type": str(rate_limits.get("plan_type") or ""),
        "primary_remaining_percent": f"{primary_remaining}%" if primary_remaining is not None else "--",
        "primary_remaining_value": primary_remaining,
        "primary_used_percent": primary_used,
        "primary_resets_at": format_reset_label(primary_resets_at, always_time=True),
        "primary_resets_at_epoch": epoch_value(primary_resets_at),
        "secondary_remaining_percent": f"{secondary_remaining}%" if secondary_remaining is not None else "--",
        "secondary_remaining_value": secondary_remaining,
        "secondary_used_percent": secondary_used,
        "secondary_resets_at": format_reset_label(secondary_resets_at),
        "secondary_resets_at_epoch": epoch_value(secondary_resets_at),
        "updated_at": str(event.get("timestamp", "")),
        "cached_at": "",
        "source_session": str(source_session or ""),
        "sync_label": "",
    }


def read_usage() -> dict[str, object]:
    latest_usage: dict[str, object] | None = None
    for path in iter_recent_session_files():
        try:
            with path.open("rb") as fh:
                size = path.stat().st_size
                fh.seek(max(0, size - 512 * 1024))
                chunk = fh.read().decode("utf-8", errors="replace")
        except OSError:
            continue
        for line in reversed(chunk.splitlines()):
            if '"rate_limits"' not in line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            usage = usage_from_event(event, path)
            if usage:
                latest_usage = newer_usage(latest_usage, usage)
                break
    with usage_lock:
        return maybe_update_usage_cache(latest_usage)


def refresh_usage_cache_once() -> dict[str, object]:
    try:
        return write_usage_cache(query_live_account_usage())
    except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
        write_log(f"Codex live account usage query failed: {exc}")
        return read_usage_cache()


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
        return "本次 --"
    primary = format_usage_delta(primary_delta) or "--"
    secondary = format_usage_delta(secondary_delta) or "--"
    return f"本次 {primary} / {secondary}"


def update_task_usage_snapshot(usage: dict[str, object] | None) -> None:
    if not usage:
        return

    primary_used = usage.get("primary_used_percent")
    secondary_used = usage.get("secondary_used_percent")
    if primary_used is None and secondary_used is None:
        return

    status_data = read_status()
    status = str(status_data.get("status", "idle"))
    if status not in {"running", "waiting", "success"}:
        return

    start_primary = status_data.get("task_usage_start_primary")
    start_secondary = status_data.get("task_usage_start_secondary")
    if start_primary is None and primary_used is not None:
        start_primary = primary_used
    if start_secondary is None and secondary_used is not None:
        start_secondary = secondary_used

    primary_delta = None
    secondary_delta = None
    if start_primary is not None and primary_used is not None:
        primary_delta = float(primary_used) - float(start_primary)
    if start_secondary is not None and secondary_used is not None:
        secondary_delta = float(secondary_used) - float(start_secondary)

    status_data["task_usage_start_primary"] = start_primary
    status_data["task_usage_start_secondary"] = start_secondary
    status_data["task_usage_end_primary"] = primary_used
    status_data["task_usage_end_secondary"] = secondary_used
    status_data["task_usage_label"] = format_task_usage_label(primary_delta, secondary_delta)
    status_data["task_usage_primary_label"] = format_usage_delta(primary_delta)
    status_data["task_usage_secondary_label"] = format_usage_delta(secondary_delta)

    with status_lock:
        STATUS_FILE.write_text(json.dumps(status_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def apply_codex_event(event: dict[str, object]) -> str:
    event_type = str(event.get("type", ""))
    payload = event.get("payload", {})
    if not isinstance(payload, dict):
        payload = {}

    payload_type = str(payload.get("type", ""))
    if event_type == "event_msg" and payload_type in {"approval_request", "permission_request", "user_input_requested"}:
        write_status("waiting", "Codex 等待用户确认")
        update_task_usage_snapshot(read_usage_cache())
        return "waiting"

    if event_type == "response_item" and payload_type == "function_call":
        arguments = str(payload.get("arguments", ""))
        if "require_escalated" in arguments:
            write_status("waiting", "Codex 等待用户确认")
            update_task_usage_snapshot(read_usage_cache())
            return "waiting"

    if event_type == "event_msg" and payload_type == "task_started":
        write_status("running", "Codex 正在处理任务")
        update_task_usage_snapshot(read_usage_cache())
        return "running"

    if event_type == "response_item" and payload_type == "function_call":
        name = str(payload.get("name", "工具"))
        write_status("running", f"Codex 正在执行 {name}")
        update_task_usage_snapshot(read_usage_cache())
        return "running"

    if event_type == "response_item" and payload_type == "function_call_output":
        write_status("running", "Codex 正在处理工具结果")
        update_task_usage_snapshot(read_usage_cache())
        return "running"

    if event_type == "response_item" and payload_type in {"reasoning", "message"}:
        phase = str(payload.get("phase", ""))
        if phase != "final_answer":
            write_status("running", "Codex 正在生成回复")
            update_task_usage_snapshot(read_usage_cache())
            return "running"
        if payload_type == "message" and str(payload.get("role", "")) == "assistant":
            return "success"

    if event_type == "event_msg" and payload_type == "agent_message":
        phase = str(payload.get("phase", ""))
        if phase != "final_answer":
            write_status("running", "Codex 正在处理任务")
            update_task_usage_snapshot(read_usage_cache())
            return "running"
        return "success"

    if event_type == "event_msg" and payload_type == "task_complete":
        return ""

    return ""


def codex_status_monitor() -> None:
    write_log(f"Codex auto monitor watching: {CODEX_SESSIONS_DIR}")
    positions: dict[Path, int] = {}
    ignored_paths: set[Path] = set()
    last_success_at = 0.0
    pending_usage_refresh: set[tuple[str, str]] = set()
    refreshed_tasks: set[tuple[str, str]] = set()
    initialized = False

    while True:
        try:
            files = iter_recent_session_files()
            if not files:
                time.sleep(1)
                continue

            if not initialized:
                TELEMETRY.rebuild(files)
                for path in files:
                    positions[path] = path.stat().st_size
                    task = TELEMETRY.task_for(path)
                    if task.status in {"running", "waiting"}:
                        pending_usage_refresh.add((str(path), task.turn_id or task.session_id))
                snapshot = TELEMETRY.snapshot()
                if snapshot["status"] in {"running", "waiting"}:
                    write_status(str(snapshot["status"]), str(snapshot["stage"]))
                    update_task_usage_snapshot(read_usage_cache())
                else:
                    write_status("idle", "Codex 空闲")
                refresh_usage_cache_once()
                initialized = True
                time.sleep(MONITOR_INTERVAL_SECONDS)
                continue

            for path in files:
                if path in ignored_paths:
                    continue

                if path not in positions:
                    positions[path] = 0

                with path.open("r", encoding="utf-8", errors="replace") as fh:
                    fh.seek(positions[path])
                    lines = fh.readlines()
                    positions[path] = fh.tell()

                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if is_approval_review_event(event):
                        ignored_paths.add(path)
                        TELEMETRY.mark_ignored(path)
                        write_log(f"Ignored approval review session: {path}")
                        break
                    if '"rate_limits"' in line:
                        usage = usage_from_event(event, path)
                        with usage_lock:
                            usage = maybe_update_usage_cache(usage)
                        update_task_usage_snapshot(usage)
                    applied_status = TELEMETRY.ingest(event, path)
                    task = TELEMETRY.task_for(path)
                    task_key = (str(path), task.turn_id or task.session_id)
                    if applied_status in {"running", "waiting"}:
                        pending_usage_refresh.add(task_key)
                        update_task_usage_snapshot(read_usage_cache())
                    elif applied_status in {"success", "error"}:
                        if applied_status == "success" and task_key in pending_usage_refresh and task_key not in refreshed_tasks:
                            usage = refresh_usage_cache_once()
                            update_task_usage_snapshot(usage)
                            refreshed_tasks.add(task_key)
                        pending_usage_refresh.discard(task_key)
                        if applied_status == "success":
                            last_success_at = time.time()

                    if applied_status:
                        snapshot = TELEMETRY.snapshot()
                        snapshot_status = str(snapshot["status"])
                        if snapshot_status in {"running", "waiting", "error"}:
                            write_status(snapshot_status, str(snapshot["stage"]))
                        elif snapshot_status == "success":
                            write_status("success", "Codex 任务完成")

            current = read_status()
            now = time.time()
            if current.get("status") == "success" and last_success_at and now - last_success_at > SUCCESS_HOLD_SECONDS:
                write_status("idle", "Codex 空闲")
                last_success_at = 0.0
            elif TELEMETRY.expire_stale(RUNNING_STALE_SECONDS):
                write_status("idle", "Codex 空闲")

        except Exception as exc:
            write_log(f"Codex auto monitor error: {exc}")

        time.sleep(MONITOR_INTERVAL_SECONDS)


class StatusHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def send_body(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        if ALLOW_CORS:
            self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def authorized(self, query: dict[str, list[str]]) -> bool:
        if not STATUS_ACCESS_TOKEN:
            return True
        supplied = query.get("token", [""])[0]
        authorization = self.headers.get("Authorization", "")
        if authorization.startswith("Bearer "):
            supplied = authorization[7:]
        return hmac.compare_digest(supplied, STATUS_ACCESS_TOKEN)

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)
        write_log(f"Request from {self.client_address[0]}:{self.client_address[1]}: GET {path}")
        if not self.authorized(query):
            self.send_body(403, b"Forbidden", "text/plain; charset=utf-8")
            write_log("Response 403")
            return

        if path == "/rainmeter":
            status_data = read_status()
            usage_data = read_usage_cache()
            task_data = TELEMETRY.public_snapshot(expose_details=EXPOSE_TASK_DETAILS)
            text = build_rainmeter_payload(status_data, usage_data, task_data)
            body = text.encode("utf-8")
            self.send_body(200, body, "text/plain; charset=utf-8")
            write_log("Response 200 rainmeter")
            return

        if path == "/usage":
            body = json.dumps(public_usage(read_usage_cache()), ensure_ascii=False, indent=2).encode("utf-8")
            self.send_body(200, body, "application/json; charset=utf-8")
            write_log("Response 200 usage")
            return

        if path == "/health":
            task_data = TELEMETRY.public_snapshot(expose_details=EXPOSE_TASK_DETAILS)
            body = json.dumps(
                {"status": "ok", "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"), "task": task_data},
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8")
            self.send_body(200, body, "application/json; charset=utf-8")
            write_log("Response 200 health")
            return

        if path != "/status":
            self.send_error(404, "Not Found")
            write_log("Response 404")
            return

        status_data = read_status()
        status_data["usage"] = public_usage(read_usage_cache())
        status_data["task"] = TELEMETRY.public_snapshot(expose_details=EXPOSE_TASK_DETAILS)
        body = json.dumps(status_data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_body(200, body, "application/json; charset=utf-8")
        write_log("Response 200 status.json")

    def log_message(self, fmt: str, *args: object) -> None:
        return


class StatusServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main() -> int:
    if not STATUS_FILE.exists():
        STATUS_FILE.write_text(json.dumps(DEFAULT_STATUS, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    try:
        server = StatusServer((HOST, PORT), StatusHandler)
    except OSError as exc:
        write_log(f"Codex status server failed to start on {HOST}:{PORT}: {exc}")
        return 1

    write_log(f"Codex status server started on {HOST}:{PORT}")
    print(f"Codex status server: http://{HOST}:{PORT}/status")
    print(f"Local computer: http://127.0.0.1:{PORT}/status")
    if HOST in {"0.0.0.0", "::"}:
        print(f"Other computer: http://THIS-COMPUTER-IP:{PORT}/status")
    else:
        print("LAN access: set HOST=0.0.0.0 before starting the server")
    print(f"Status file: {STATUS_FILE}")
    print(f"Log file: {LOG_FILE}")
    print(f"Codex usage sessions: {CODEX_SESSIONS_DIR}")
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

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
