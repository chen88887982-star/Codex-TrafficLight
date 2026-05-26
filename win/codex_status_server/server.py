#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
STATUS_FILE = BASE_DIR / "status.json"
LOG_FILE = BASE_DIR / "status-server.log"
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8765"))

DEFAULT_STATUS = {
    "status": "idle",
    "message": "Codex 空闲",
    "updated_at": "1970-01-01T00:00:00+00:00",
}


def write_log(message: str) -> None:
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    print(message, flush=True)
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def read_status() -> dict[str, str]:
    if not STATUS_FILE.exists():
        return DEFAULT_STATUS

    try:
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

        if self.path.rstrip("/") != "/status":
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
