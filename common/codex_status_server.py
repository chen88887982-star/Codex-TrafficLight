#!/usr/bin/env python3
from __future__ import annotations

import hmac
import json
import math
import os
import queue
import shlex
import shutil
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

from codex_telemetry import CodexTelemetry  # noqa: E402
from service_runtime import (  # noqa: E402
    JsonlFollower,
    RotatingTextLog,
    SingleFlightWorker,
    TaskRefreshTracker,
    atomic_write_json,
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


PRIVATE_SETTINGS = load_private_settings()
STATUS_FILE = BASE_DIR / "status.json"
USAGE_CACHE_FILE = BASE_DIR / "usage-cache.json"
LOG_FILE = BASE_DIR / "status-server.log"
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = read_env_int("PORT", 8765, 1, 65535)
AUTO_MONITOR = read_env_bool("AUTO_MONITOR_CODEX", True)
CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
CODEX_SESSIONS_DIR = CODEX_HOME / "sessions"
SUCCESS_HOLD_SECONDS = read_env_int("SUCCESS_HOLD_SECONDS", 45, 0, 3600)
MONITOR_INTERVAL_SECONDS = read_env_float("MONITOR_INTERVAL_SECONDS", 0.25, 0.05, 60.0)
RUNNING_STALE_SECONDS = read_env_int("RUNNING_STALE_SECONDS", 300, 5, 86400)
USAGE_STALE_SECONDS = read_env_int("USAGE_STALE_SECONDS", 900, 30, 86400)
ACCOUNT_QUERY_TIMEOUT_SECONDS = read_env_float("ACCOUNT_QUERY_TIMEOUT_SECONDS", 45.0, 1.0, 300.0)
LOG_MAX_BYTES = read_env_int("LOG_MAX_BYTES", 5 * 1024 * 1024, 1024, 1024 * 1024 * 1024)
LOG_BACKUP_COUNT = read_env_int("LOG_BACKUP_COUNT", 3, 0, 100)
GIT_CACHE_SECONDS = read_env_float("GIT_CACHE_SECONDS", 2.0, 0.0, 60.0)
GIT_TIMEOUT_SECONDS = read_env_float("GIT_TIMEOUT_SECONDS", 2.5, 0.1, 30.0)
TASK_STATS_SCOPE = read_env_choice("TASK_STATS_SCOPE", "task", {"turn", "task", "service"})
GIT_STATS_EXCLUDE = read_env_patterns("GIT_STATS_EXCLUDE", ".DS_Store")
GIT_INCLUDE_MODE_ONLY = read_env_bool("GIT_INCLUDE_MODE_ONLY", False)
CODEX_COMMAND = os.environ.get("CODEX_COMMAND", "").strip()
STATUS_ACCESS_TOKEN = os.environ.get("STATUS_ACCESS_TOKEN", str(PRIVATE_SETTINGS.get("access_token") or ""))
ALLOW_CORS = read_env_bool("ALLOW_CORS", bool(PRIVATE_SETTINGS.get("allow_cors")))
EXPOSE_TASK_DETAILS = resolve_expose_task_details(PRIVATE_SETTINGS, os.environ)
TELEMETRY = CodexTelemetry(
    CODEX_HOME,
    git_cache_seconds=GIT_CACHE_SECONDS,
    git_timeout_seconds=GIT_TIMEOUT_SECONDS,
    task_stats_scope=TASK_STATS_SCOPE,
    git_exclude_patterns=GIT_STATS_EXCLUDE,
    include_mode_only=GIT_INCLUDE_MODE_ONLY,
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


status_lock = threading.RLock()
usage_lock = threading.RLock()
service_log = RotatingTextLog(LOG_FILE, max_bytes=LOG_MAX_BYTES, backups=LOG_BACKUP_COUNT)


def write_log(message: str) -> None:
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    print(message, flush=True)
    try:
        service_log.write(line)
    except OSError as exc:
        print(f"status-server.log write failed: {exc}", flush=True)


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
    with status_lock:
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
        atomic_write_json(STATUS_FILE, payload)


def read_status() -> dict[str, object]:
    if not STATUS_FILE.exists():
        return DEFAULT_STATUS.copy()

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


def iter_recent_session_files(limit: int = 20) -> list[Path]:
    if not CODEX_SESSIONS_DIR.exists():
        return []
    candidates: list[tuple[float, Path]] = []
    for path in CODEX_SESSIONS_DIR.rglob("rollout-*.jsonl"):
        try:
            candidates.append((path.stat().st_mtime, path))
        except FileNotFoundError:
            continue
    candidates.sort(key=lambda item: item[0], reverse=True)
    return [path for _, path in candidates[:limit]]


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
            atomic_write_json(USAGE_CACHE_FILE, usage)
        except OSError as exc:
            write_log(f"usage-cache.json write failed: {exc}")
            return read_usage_cache()
        return usage


def rainmeter_value(value: object) -> str:
    if value is None:
        return "-1"
    return str(value)


def build_rainmeter_payload(
    status_data: dict[str, object], usage_data: dict[str, object], task_data: dict[str, object]
) -> str:
    status_codes = {"idle": "0", "running": "1", "waiting": "2", "success": "3", "error": "4"}
    active_label = str(task_data.get("other_active_project") or "")
    model_label = " ".join(
        value for value in (str(task_data.get("model") or ""), str(task_data.get("reasoning_effort") or "")) if value
    )
    return "{code}|{message}|{updated_at}|{primary_remaining}|{primary_reset}|{secondary_remaining}|{secondary_reset}|{task_elapsed}|{primary_value}|{secondary_value}|{sync_label}|{task_usage_primary}|{task_usage_secondary}|{project}|{task_title}|{active_label}|{git_branch}|{git_change}|{git_state}|{token_label}|{context_label}|{health_label}|{credits_available}|{credits_label}|{model_label}|{git_cumulative}".format(
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
            task_data.get("git_sync_label") or task_data.get("git_cumulative_label") or "待同步 --"
        ),
    )


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


def resolve_codex_command() -> list[str]:
    if CODEX_COMMAND:
        return shlex.split(CODEX_COMMAND, posix=os.name != "nt")

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

    raise RuntimeError(
        "Codex CLI was not found. Install/open Codex Desktop, add codex to PATH, "
        "or set CODEX_COMMAND to the full Codex executable path."
    )


def query_live_account_usage() -> dict[str, object]:
    process = subprocess.Popen(
        resolve_codex_command() + ["app-server", "--stdio"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )
    messages: queue.Queue[dict[str, object]] = queue.Queue()

    def reader() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            try:
                item = json.loads(line)
                if isinstance(item, dict):
                    messages.put(item)
            except json.JSONDecodeError:
                continue

    reader_thread = threading.Thread(target=reader, name="codex-account-reader", daemon=True)
    reader_thread.start()
    deadline = time.monotonic() + ACCOUNT_QUERY_TIMEOUT_SECONDS

    def request(request_id: int, method: str, params: object) -> dict[str, object]:
        assert process.stdin is not None
        process.stdin.write(json.dumps({"id": request_id, "method": method, "params": params}) + "\n")
        process.stdin.flush()
        while time.monotonic() < deadline:
            try:
                item = messages.get(timeout=min(0.25, max(0.01, deadline - time.monotonic())))
            except queue.Empty:
                continue
            if item.get("id") == request_id:
                result = item.get("result")
                if isinstance(result, dict):
                    return result
                raise RuntimeError(str(item.get("error") or "Codex account query failed"))
        raise TimeoutError("Codex account query timed out")

    account_usage: dict[str, object] = {}
    try:
        request(1, "initialize", {"clientInfo": {"name": "Codex-TrafficLight", "version": "1.0"}})
        limits = request(2, "account/rateLimits/read", None)
        try:
            account_usage = request(3, "account/usage/read", None)
        except (RuntimeError, TimeoutError) as exc:
            write_log(f"Codex credits query skipped: {exc}")
    finally:
        if process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        reader_thread.join(timeout=1)
        if process.stdout is not None:
            process.stdout.close()
    snapshots = limits.get("rateLimitsByLimitId")
    snapshot = snapshots.get("codex") if isinstance(snapshots, dict) else limits.get("rateLimits")
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("primary"), dict):
        raise RuntimeError("Codex returned no primary rate limit")
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

    with status_lock:
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
        atomic_write_json(STATUS_FILE, status_data)


def refresh_usage_and_task_snapshot() -> None:
    try:
        update_task_usage_snapshot(refresh_usage_cache_once())
    except OSError as exc:
        write_log(f"Codex usage snapshot update failed: {exc}")


usage_refresh_worker = SingleFlightWorker(refresh_usage_and_task_snapshot, name="codex-usage-refresh")


def codex_status_monitor() -> None:
    write_log(f"Codex auto monitor watching: {CODEX_SESSIONS_DIR}")
    follower = JsonlFollower()
    ignored_paths: set[Path] = set()
    last_success_at = 0.0
    refresh_tracker = TaskRefreshTracker()
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
                    try:
                        follower.start_at_end(path)
                    except FileNotFoundError:
                        continue
                    task = TELEMETRY.task_for(path)
                    if task.status in {"running", "waiting"}:
                        refresh_tracker.mark_active((str(path), task.turn_id or task.session_id))
                snapshot = TELEMETRY.snapshot()
                if snapshot["status"] in {"running", "waiting"}:
                    write_status(str(snapshot["status"]), str(snapshot["stage"]))
                    update_task_usage_snapshot(read_usage_cache())
                else:
                    write_status("idle", "Codex 空闲")
                usage_refresh_worker.request()
                initialized = True
                time.sleep(MONITOR_INTERVAL_SECONDS)
                continue

            for path in files:
                if path in ignored_paths:
                    continue

                for line in follower.read_lines(path):
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
                    applied_status = TELEMETRY.ingest(event, path)
                    task = TELEMETRY.task_for(path)
                    task_key = (str(path), task.turn_id or task.session_id)
                    if applied_status in {"running", "waiting"}:
                        refresh_tracker.mark_active(task_key)
                        update_task_usage_snapshot(read_usage_cache())
                    elif applied_status in {"success", "error"}:
                        if refresh_tracker.complete(task_key, success=applied_status == "success"):
                            usage_refresh_worker.request()
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
            watched_paths = set(files)
            follower.prune(watched_paths)
            ignored_paths.intersection_update(watched_paths)
            refresh_tracker.prune(watched_paths)
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
        if not self.authorized(query):
            self.send_body(403, b"Forbidden", "text/plain; charset=utf-8")
            write_log(f"Request denied from {self.client_address[0]}: GET {path}")
            return

        if path == "/rainmeter":
            status_data = read_status()
            usage_data = read_usage_cache()
            task_data = TELEMETRY.public_snapshot(expose_details=EXPOSE_TASK_DETAILS)
            text = build_rainmeter_payload(status_data, usage_data, task_data)
            body = text.encode("utf-8")
            self.send_body(200, body, "text/plain; charset=utf-8")
            return

        if path == "/usage":
            body = json.dumps(public_usage(read_usage_cache()), ensure_ascii=False, indent=2).encode("utf-8")
            self.send_body(200, body, "application/json; charset=utf-8")
            return

        if path == "/health":
            task_data = TELEMETRY.public_snapshot(expose_details=EXPOSE_TASK_DETAILS)
            body = json.dumps(
                {
                    "status": "ok",
                    "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "task": task_data,
                },
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8")
            self.send_body(200, body, "application/json; charset=utf-8")
            return

        if path != "/status":
            self.send_error(404, "Not Found")
            write_log(f"Unknown request from {self.client_address[0]}: GET {path}")
            return

        status_data = read_status()
        status_data["usage"] = public_usage(read_usage_cache())
        status_data["task"] = TELEMETRY.public_snapshot(expose_details=EXPOSE_TASK_DETAILS)
        body = json.dumps(status_data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_body(200, body, "application/json; charset=utf-8")

    def log_message(self, fmt: str, *args: object) -> None:
        return


class StatusServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main() -> int:
    if not STATUS_FILE.exists():
        atomic_write_json(STATUS_FILE, DEFAULT_STATUS)

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
