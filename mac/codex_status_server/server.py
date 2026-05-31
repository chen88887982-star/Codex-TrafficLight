#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import os
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
STATUS_FILE = BASE_DIR / "status.json"
USAGE_CACHE_FILE = BASE_DIR / "usage-cache.json"
LOG_FILE = BASE_DIR / "status-server.log"
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8765"))
AUTO_MONITOR = os.environ.get("AUTO_MONITOR_CODEX", "1") != "0"
CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
CODEX_SESSIONS_DIR = CODEX_HOME / "sessions"
SUCCESS_HOLD_SECONDS = int(os.environ.get("SUCCESS_HOLD_SECONDS", "45"))
MONITOR_INTERVAL_SECONDS = float(os.environ.get("MONITOR_INTERVAL_SECONDS", "0.25"))
RUNNING_STALE_SECONDS = int(os.environ.get("RUNNING_STALE_SECONDS", "300"))
USAGE_STALE_SECONDS = int(os.environ.get("USAGE_STALE_SECONDS", "900"))

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
    "secondary_remaining_percent": "",
    "secondary_remaining_value": None,
    "secondary_used_percent": None,
    "secondary_resets_at": "",
    "updated_at": "",
    "cached_at": "",
    "source_session": "",
    "sync_label": "等待 Codex 写入额度",
}


status_lock = threading.Lock()


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


def format_reset_label(epoch_seconds: object) -> str:
    try:
        reset_at = datetime.fromtimestamp(int(epoch_seconds)).astimezone()
    except (TypeError, ValueError, OSError):
        return "--"
    now = datetime.now().astimezone()
    if reset_at.date() == now.date():
        return reset_at.strftime("%H:%M")
    return f"{reset_at.month}月{reset_at.day}日"


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


def parse_timestamp(value: object) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def format_sync_label(usage: dict[str, object]) -> str:
    if not usage.get("available"):
        return "等待 Codex 写入额度"

    cached_at = str(usage.get("cached_at") or "")
    timestamp = parse_timestamp(cached_at or usage.get("updated_at"))
    if not timestamp:
        return "最近同步"

    updated = datetime.fromtimestamp(timestamp).astimezone()
    label_time = updated.strftime("%H:%M")
    if time.time() - timestamp > USAGE_STALE_SECONDS:
        return f"可能滞后 {label_time}"
    return f"更新 {label_time}"


def read_usage_cache() -> dict[str, object]:
    if not USAGE_CACHE_FILE.exists():
        return DEFAULT_USAGE.copy()
    try:
        data = json.loads(USAGE_CACHE_FILE.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        write_log(f"usage-cache.json read failed: {exc}")
        return DEFAULT_USAGE.copy()

    usage = DEFAULT_USAGE.copy()
    usage.update(data)
    usage["sync_label"] = format_sync_label(usage)
    return usage


def write_usage_cache(usage: dict[str, object]) -> dict[str, object]:
    usage = usage.copy()
    usage["cached_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    usage["sync_label"] = format_sync_label(usage)
    try:
        USAGE_CACHE_FILE.write_text(json.dumps(usage, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        write_log(f"usage-cache.json write failed: {exc}")
    return usage


def maybe_update_usage_cache(usage: dict[str, object] | None) -> dict[str, object]:
    cached = read_usage_cache()
    if not usage:
        return cached

    usage_timestamp = parse_timestamp(usage.get("updated_at"))
    cached_timestamp = parse_timestamp(cached.get("updated_at"))
    if usage_timestamp > cached_timestamp or not cached.get("available"):
        return write_usage_cache(usage)
    return cached


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

    return {
        "available": True,
        "plan_type": str(rate_limits.get("plan_type") or ""),
        "primary_remaining_percent": f"{primary_remaining}%" if primary_remaining is not None else "--",
        "primary_remaining_value": primary_remaining,
        "primary_used_percent": primary_used,
        "primary_resets_at": format_reset_label(primary.get("resets_at")),
        "secondary_remaining_percent": f"{secondary_remaining}%" if secondary_remaining is not None else "--",
        "secondary_remaining_value": secondary_remaining,
        "secondary_used_percent": secondary_used,
        "secondary_resets_at": format_reset_label(secondary.get("resets_at")),
        "updated_at": str(event.get("timestamp", "")),
        "cached_at": "",
        "source_session": str(source_session or ""),
        "sync_label": "",
    }


def read_usage() -> dict[str, object]:
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
                return maybe_update_usage_cache(usage)
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
    last_running_at = 0.0
    initialized = False

    while True:
        try:
            files = iter_recent_session_files()
            if not files:
                time.sleep(1)
                continue

            if not initialized:
                for path in files:
                    positions[path] = path.stat().st_size
                write_status("idle", "Codex 空闲")
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
                        write_log(f"Ignored approval review session: {path}")
                        break
                    if '"rate_limits"' in line:
                        usage = usage_from_event(event, path)
                        maybe_update_usage_cache(usage)
                        update_task_usage_snapshot(usage)
                    applied_status = apply_codex_event(event)
                    if applied_status in {"running", "waiting"}:
                        last_running_at = time.time()
                    elif applied_status == "success":
                        write_status("success", "Codex 任务完成")
                        update_task_usage_snapshot(read_usage_cache())
                        last_success_at = time.time()

            current = read_status()
            now = time.time()
            if current.get("status") == "success" and last_success_at and now - last_success_at > SUCCESS_HOLD_SECONDS:
                write_status("idle", "Codex 空闲")
                last_success_at = 0.0
            elif current.get("status") == "running" and last_running_at and now - last_running_at > RUNNING_STALE_SECONDS:
                write_status("idle", "Codex 空闲")
                last_running_at = 0.0

        except Exception as exc:
            write_log(f"Codex auto monitor error: {exc}")

        time.sleep(MONITOR_INTERVAL_SECONDS)


class StatusHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        write_log(f"Request from {self.client_address[0]}:{self.client_address[1]}: {self.requestline}")

        path = self.path.rstrip("/")
        if path == "/rainmeter":
            status_data = read_status()
            usage_data = read_usage()
            is_idle = str(status_data.get("status", "idle")) == "idle"
            status_codes = {
                "idle": "0",
                "running": "1",
                "waiting": "2",
                "success": "3",
                "error": "4",
            }
            text = "{code}|{message}|{updated_at}|{primary_remaining}|{primary_reset}|{secondary_remaining}|{secondary_reset}|{task_elapsed}|{primary_value}|{secondary_value}|{sync_label}|{task_usage_primary}|{task_usage_secondary}".format(
                code=status_codes.get(status_data["status"], "4"),
                message=clean_field(status_data["message"]),
                updated_at=clean_field(status_data["updated_at"]),
                primary_remaining=clean_field(usage_data["primary_remaining_percent"] or "--"),
                primary_reset=clean_field(usage_data["primary_resets_at"] or "--"),
                secondary_remaining=clean_field(usage_data["secondary_remaining_percent"] or "--"),
                secondary_reset=clean_field(usage_data["secondary_resets_at"] or "--"),
                task_elapsed=clean_field(task_elapsed_label(status_data)),
                primary_value=clean_field(str(usage_data.get("primary_remaining_value") or 0)),
                secondary_value=clean_field(str(usage_data.get("secondary_remaining_value") or 0)),
                sync_label=clean_field(usage_data.get("sync_label") or ""),
                task_usage_primary="" if is_idle else clean_field(status_data.get("task_usage_primary_label") or ""),
                task_usage_secondary="" if is_idle else clean_field(status_data.get("task_usage_secondary_label") or ""),
            )
            body = text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            write_log("Response 200 rainmeter")
            return

        if path == "/usage":
            body = json.dumps(read_usage(), ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            write_log("Response 200 usage")
            return

        if path != "/status":
            self.send_error(404, "Not Found")
            write_log("Response 404")
            return

        status_data = read_status()
        status_data["usage"] = read_usage()
        body = json.dumps(status_data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
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
    print(f"Other computer: http://THIS-COMPUTER-IP:{PORT}/status")
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
