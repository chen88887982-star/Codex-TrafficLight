"""HTTP transport for read-only snapshots and bounded monitor preferences."""

from __future__ import annotations

import ipaddress
import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlsplit

from dashboard import dashboard_asset
from state_store import reject_json_constant


class StatusHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    app = None

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(10)

    def send_body(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'",
        )
        if self.app.ALLOW_CORS:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)
        self.close_connection = True

    def send_json(self, status: int, payload: object) -> None:
        self.send_body(
            status,
            json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def authorized(self, query: dict[str, list[str]]) -> bool:
        return self.app.request_authorized(self.client_address[0], query, self.headers.get("Authorization", ""))

    def mutation_authorized(self, query: dict[str, list[str]]) -> bool:
        if not self.authorized(query):
            return False
        try:
            local = ipaddress.ip_address(self.client_address[0]).is_loopback
        except ValueError:
            local = False
        # LAN preference writes require the explicitly configured access token.
        if not local and not self.app.STATUS_ACCESS_TOKEN:
            return False
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        if origin and urlsplit(origin).netloc != host:
            return False
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            return False
        if local:
            hostname = urlsplit("http://" + host).hostname
            if hostname not in {"localhost", "127.0.0.1", "::1"}:
                return False
        return True

    def do_OPTIONS(self) -> None:
        if self.app.ALLOW_CORS:
            self.send_body(204, b"", "text/plain")
        else:
            self.send_json(403, {"error": "跨域访问未开启"})

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)
        asset = dashboard_asset(path)
        if asset:
            self.send_body(200, *asset)
            return
        if not self.authorized(query):
            self.send_json(403, {"error": "请提供访问令牌"})
            return
        try:
            if path.startswith("/api/"):
                status, result = self.app.api_dispatch("GET", path, query, {})
                self.send_json(status, result)
                return
            snapshot = self.app.dashboard_snapshot()
            if path == "/rainmeter":
                task = snapshot["task"].copy()
                task["health_label"] = snapshot["health"]["label"]
                self.send_body(
                    200,
                    self.app.build_rainmeter_payload(snapshot["status"], snapshot["usage"], task).encode("utf-8"),
                    "text/plain; charset=utf-8",
                )
            elif path == "/tasks":
                self.send_body(
                    200, self.app.build_tasks_payload(snapshot["task"]).encode("utf-8"), "text/plain; charset=utf-8"
                )
            elif path == "/usage":
                self.send_json(200, snapshot["usage"])
            elif path == "/health":
                self.send_json(200, {**snapshot["health"], "task": snapshot["task"]})
            elif path == "/status":
                self.send_json(
                    200,
                    {
                        **snapshot["status"],
                        "usage": snapshot["usage"],
                        "task": snapshot["task"],
                        "health": snapshot["health"],
                    },
                )
            else:
                self.send_json(404, {"error": "接口不存在"})
        except (ValueError, TypeError, KeyError) as exc:
            self.send_json(400, {"error": str(exc)[:160]})
        except Exception:
            self.send_json(503, {"error": "服务暂时不可用，请查看体检报告"})

    def do_POST(self) -> None:
        parsed = urlsplit(self.path)
        query = parse_qs(parsed.query)
        if not self.mutation_authorized(query):
            self.send_json(403, {"error": "操作需同源访问；远程操作需配置服务访问令牌"})
            return
        try:
            if self.headers.get("Transfer-Encoding"):
                raise ValueError("不支持分块请求")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= 16 * 1024:
                self.send_json(413, {"error": "请求过大"})
                return
            if length and self.headers.get_content_type() != "application/json":
                raise ValueError("请使用 JSON 请求")
            payload = json.loads(self.rfile.read(length), parse_constant=reject_json_constant) if length else {}
            if not isinstance(payload, dict):
                raise ValueError("请求必须为 JSON 对象")
            status, result = self.app.api_dispatch("POST", parsed.path.rstrip("/"), query, payload)
            self.send_json(status, result)
        except (ValueError, TypeError, KeyError) as exc:
            self.send_json(400, {"error": str(exc)[:160]})
        except OSError:
            self.send_json(503, {"error": "配置保存失败，请检查运行目录"})
        except Exception:
            self.send_json(503, {"error": "操作失败，请查看体检报告"})

    def log_message(self, fmt: str, *args: object) -> None:
        return
