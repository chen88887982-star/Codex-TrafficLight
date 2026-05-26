#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
STATUS_FILE = BASE_DIR / "status.json"
LOG_FILE = BASE_DIR / "status-server.log"
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8765"))
AUTO_MONITOR = os.environ.get("AUTO_MONITOR_CODEX", "1") != "0"
CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
CODEX_SESSIONS_DIR = CODEX_HOME / "sessions"
SUCCESS_HOLD_SECONDS = int(os.environ.get("SUCCESS_HOLD_SECONDS", "45"))
MONITOR_INTERVAL_SECONDS = float(os.environ.get("MONITOR_INTERVAL_SECONDS", "0.25"))
RUNNING_STALE_SECONDS = int(os.environ.get("RUNNING_STALE_SECONDS", "300"))

DEFAULT_STATUS = {
    "status": "idle",
    "message": "Codex 空闲",
    "updated_at": "1970-01-01T00:00:00+00:00",
}


status_lock = threading.Lock()


def write_log(message: str) -> None:
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    print(message, flush=True)
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def write_status(status: str, message: str) -> None:
    payload = {
        "status": status,
        "message": message,
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    with status_lock:
        STATUS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_status() -> dict[str, str]:
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
    }


class StatusHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        write_log(f"Request from {self.client_address[0]}:{self.client_address[1]}: {self.requestline}")

        path = self.path.rstrip("/")
        if path == "/rainmeter":
            status_data = read_status()
            status_codes = {
                "idle": "0",
                "running": "1",
                "waiting": "2",
                "success": "3",
                "error": "4",
            }
            text = "{code}|{message}|{updated_at}".format(
                code=status_codes.get(status_data["status"], "4"),
                message=status_data["message"].replace("|", "/").replace("\r", " ").replace("\n", " "),
                updated_at=status_data["updated_at"].replace("|", "/").replace("\r", " ").replace("\n", " "),
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

        if path != "/status":
            body = b"Not Found"
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            write_log("Response 404")
            return

        body = json.dumps(read_status(), ensure_ascii=False, indent=2).encode("utf-8")
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


def iter_recent_session_files() -> list[Path]:
    if not CODEX_SESSIONS_DIR.exists():
        return []
    files = list(CODEX_SESSIONS_DIR.rglob("rollout-*.jsonl"))
    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return files[:5]


def apply_codex_event(event: dict[str, object]) -> str:
    event_type = str(event.get("type", ""))
    payload = event.get("payload", {})
    if not isinstance(payload, dict):
        payload = {}

    payload_type = str(payload.get("type", ""))
    if event_type == "event_msg" and payload_type in {"approval_request", "permission_request", "user_input_requested"}:
        write_status("waiting", "Codex 等待用户确认")
        return "waiting"

    if event_type == "response_item" and payload_type == "function_call":
        arguments = str(payload.get("arguments", ""))
        if "require_escalated" in arguments:
            write_status("waiting", "Codex 等待用户确认")
            return "waiting"

    if event_type == "event_msg" and payload_type == "task_started":
        write_status("running", "Codex 正在处理任务")
        return "running"

    if event_type == "response_item" and payload_type == "function_call":
        name = str(payload.get("name", "工具"))
        write_status("running", f"Codex 正在执行 {name}")
        return "running"

    if event_type == "response_item" and payload_type == "function_call_output":
        write_status("running", "Codex 正在处理工具结果")
        return "running"

    if event_type == "response_item" and payload_type in {"reasoning", "message"}:
        phase = str(payload.get("phase", ""))
        if phase != "final_answer":
            write_status("running", "Codex 正在生成回复")
            return "running"

    if event_type == "event_msg" and payload_type == "agent_message":
        phase = str(payload.get("phase", ""))
        if phase != "final_answer":
            write_status("running", "Codex 正在处理任务")
            return "running"

    if event_type == "event_msg" and payload_type == "task_complete":
        write_status("success", "Codex 任务完成")
        return "success"

    return ""


def codex_status_monitor() -> None:
    write_log(f"Codex auto monitor watching: {CODEX_SESSIONS_DIR}")
    positions: dict[Path, int] = {}
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
                    applied_status = apply_codex_event(event)
                    if applied_status in {"running", "waiting"}:
                        last_running_at = time.time()
                    elif applied_status == "success":
                        last_success_at = time.time()

            current = read_status()
            if current.get("status") == "success" and last_success_at and time.time() - last_success_at > SUCCESS_HOLD_SECONDS:
                write_status("idle", "Codex 空闲")
                last_success_at = 0.0
            elif current.get("status") == "running" and last_running_at and time.time() - last_running_at > RUNNING_STALE_SECONDS:
                write_status("idle", "Codex 空闲")
                last_running_at = 0.0

        except Exception as exc:
            write_log(f"Codex auto monitor error: {exc}")

        time.sleep(MONITOR_INTERVAL_SECONDS)


def main() -> int:
    if not STATUS_FILE.exists():
        STATUS_FILE.write_text(json.dumps(DEFAULT_STATUS, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    try:
        server = StatusServer((HOST, PORT), StatusHandler)
    except OSError as exc:
        write_log(f"Codex status server failed to start on {HOST}:{PORT}: {exc}")
        return 1

    write_log(f"Codex status server started on {HOST}:{PORT}")
    print(f"Same Windows: http://127.0.0.1:{PORT}/status")
    print(f"Other computer: http://THIS-WINDOWS-IP:{PORT}/status")
    print(f"Status file: {STATUS_FILE}")
    print(f"Log file: {LOG_FILE}")
    if AUTO_MONITOR:
        threading.Thread(target=codex_status_monitor, name="codex-status-monitor", daemon=True).start()
        print(f"Auto monitor: {CODEX_SESSIONS_DIR}")
    else:
        print("Auto monitor: disabled")
    print("按 Ctrl+C 或关闭窗口停止服务。")

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
