from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

import codex_status_server as service
import service_monitor
from codex_telemetry import CodexTelemetry
from peer_services import PeerServiceManager
from state_store import JsonObjectStore
from usage_client import split_command
from usage_data import epoch_value, format_reset_label, parse_usage_window, remaining_value, used_percent_value


class ServerDataTests(unittest.TestCase):
    def test_monitor_keeps_valid_completion_after_malformed_records_in_same_batch(self) -> None:
        class StopMonitor(BaseException):
            pass

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "rollout-test.jsonl"
            now = datetime.now(timezone.utc).isoformat()
            events = [
                {"type": "session_meta", "timestamp": now, "payload": {"id": "one", "cwd": temporary}},
                {"type": "event_msg", "timestamp": now, "payload": {"type": "task_started", "turn_id": "turn"}},
            ]
            path.write_text("".join(json.dumps(item) + "\n" for item in events))
            state = {"status": "idle"}

            def write_status(status: str, _message: str) -> None:
                state["status"] = status

            def fallback(event: dict[str, object], _path: Path) -> None:
                if event.get("type") == "bad":
                    raise ValueError("bad record")

            def pause(_seconds: float) -> None:
                if state["status"] == "success":
                    raise StopMonitor()
                with path.open("a") as handle:
                    handle.write('[]\nnull\n{"type":"bad"}\n')
                    handle.write(
                        json.dumps(
                            {
                                "type": "event_msg",
                                "timestamp": now,
                                "payload": {"type": "task_complete", "turn_id": "turn"},
                            }
                        )
                        + "\n"
                    )

            app = SimpleNamespace(
                CODEX_SESSIONS_DIR=root,
                TELEMETRY=CodexTelemetry(root),
                USAGE_REFRESH_INTERVAL_SECONDS=0,
                USAGE_BUSY_REFRESH_SECONDS=0,
                SESSION_DISCOVERY_INTERVAL_SECONDS=10,
                MONITOR_INTERVAL_SECONDS=1,
                SUCCESS_HOLD_SECONDS=10,
                ERROR_HOLD_SECONDS=10,
                RUNNING_STALE_SECONDS=300,
                usage_refresh_worker=SimpleNamespace(request=Mock()),
                NOTIFIER=SimpleNamespace(notify=Mock()),
                iter_recent_session_files=lambda: [path],
                write_log=Mock(),
                update_monitor_health=Mock(),
                write_status=write_status,
                read_status=lambda: state.copy(),
                read_usage_cache=lambda: {},
                update_task_usage_snapshot=Mock(),
                is_approval_review_event=lambda event: False,
                consider_session_usage_fallback=fallback,
            )
            clock = SimpleNamespace(time=time.time, monotonic=time.monotonic, sleep=pause)
            with patch.object(service_monitor, "time", clock), self.assertRaises(StopMonitor):
                service_monitor.run_monitor(app)
            self.assertEqual(app.TELEMETRY.task_for(path).status, "success")
            self.assertEqual(state["status"], "success")
            app.NOTIFIER.notify.assert_called_once_with("success", "turn", root.name)
            self.assertTrue(any("Skipped invalid session record" in str(call) for call in app.write_log.call_args_list))

    def test_runtime_json_wrong_types_keep_last_good_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "usage-cache.json"
            good = {"source": "session_event", "available": True, "primary_used_percent": 28}
            with (
                patch.object(service, "USAGE_CACHE_FILE", path),
                patch.object(service, "state_store", JsonObjectStore()),
            ):
                path.write_text(json.dumps(good))
                self.assertEqual(service.read_usage_cache()["primary_remaining_value"], 72)
                for bad in (
                    [],
                    None,
                    "text",
                    {"source": "other"},
                    {**good, "primary_used_percent": "NaN"},
                    {**good, "unexpected": {"value": float("nan")}},
                    {**good, "unexpected": float("inf")},
                ):
                    path.write_text(json.dumps(bad))
                    self.assertEqual(service.read_usage_cache()["primary_remaining_value"], 72)
                self.assertTrue(service.state_store.errors())

    def test_invalid_status_numbers_are_safe_and_wrong_json_does_not_crash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "status.json"
            with patch.object(service, "STATUS_FILE", path), patch.object(service, "state_store", JsonObjectStore()):
                path.write_text('{"status":"running","running_since":"NaN","last_elapsed_seconds":"bad"}')
                state = service.read_status()
                self.assertEqual(state["running_since"], 0)
                self.assertEqual(state["last_elapsed_seconds"], 0)
                for bad in ("[]", "null", '"text"'):
                    path.write_text(bad)
                    self.assertEqual(service.read_status()["status"], "running")

    def test_nonfinite_window_values_are_not_reported_as_real_usage(self) -> None:
        for value in (True, "nan", float("inf"), float("-inf")):
            self.assertIsNone(remaining_value(value))
            self.assertIsNone(used_percent_value(value))
        self.assertIsNone(epoch_value(float("inf")))
        self.assertIsNone(remaining_value(10**10000))
        self.assertIsNone(used_percent_value(10**10000))
        self.assertEqual(format_reset_label(10**50), "--")
        self.assertEqual(
            parse_usage_window({"usedPercent": 20, "resetsAt": 10**50}, "primary")["primary_remaining_value"], 80
        )

    def test_windows_override_handles_quoted_and_unquoted_executable_paths(self) -> None:
        path = r"C:\Program Files\Codex\codex.exe"
        self.assertEqual(split_command(path, windows=True), [path])
        self.assertEqual(
            split_command('"' + path + '" --config "value with spaces"', windows=True),
            [path, "--config", "value with spaces"],
        )
        self.assertEqual(split_command(path + " --verbose", windows=True), [path, "--verbose"])

    def test_app_server_query_acknowledges_initialize_without_starting_a_turn(self) -> None:
        helper = """
import json, sys
initialized = False
for line in sys.stdin:
    request = json.loads(line)
    method = request['method']
    if method == 'initialized':
        initialized = True
        continue
    identifier = request['id']
    if method == 'initialize':
        result = {}
    elif method == 'account/rateLimits/read' and initialized:
        result = {'rateLimitsByLimitId': {'codex': {'primary': {'usedPercent': 37, 'windowDurationMins': 300}, 'credits': {'balance': 12}}}}
    elif method == 'account/usage/read':
        result = {'summary': {'lifetimeTokens': 999}}
    else:
        print(json.dumps({'id': identifier, 'error': {'message': 'unexpected method'}}), flush=True)
        continue
    print(json.dumps({'id': identifier, 'result': result}), flush=True)
"""
        with patch.object(service, "resolve_codex_command", return_value=[sys.executable, "-c", helper]):
            result = service.query_live_account_usage()
        self.assertEqual(result["primary_remaining_value"], 63)
        self.assertEqual(result["credits_label"], "12")


class HttpUpgradeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        root = Path(self.folder.name)
        self.patches = [
            patch.object(service, "STATUS_FILE", root / "status.json"),
            patch.object(service, "USAGE_CACHE_FILE", root / "usage-cache.json"),
            patch.object(service, "AUTO_MONITOR", False),
            patch.object(service, "state_store", JsonObjectStore()),
            patch.object(service, "TELEMETRY", CodexTelemetry(root, history_path=root / "history.sqlite3")),
            patch.object(service, "PEER_SERVICES", PeerServiceManager(root / "peers.json")),
        ]
        for item in self.patches:
            item.start()
        self.server = service.StatusServer(("127.0.0.1", 0), service.StatusHandler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.opener = build_opener(ProxyHandler({}))

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        for item in reversed(self.patches):
            item.stop()
        self.folder.cleanup()

    def request(
        self, path: str, *, method: str = "GET", data: object = None, headers: dict[str, str] | None = None
    ) -> tuple[int, bytes, object]:
        body = json.dumps(data).encode() if data is not None else None
        values = {"Content-Type": "application/json", **(headers or {})}
        request = Request(f"http://127.0.0.1:{self.port}{path}", data=body, headers=values, method=method)
        try:
            response = self.opener.open(request, timeout=3)
        except HTTPError as error:
            response = error
        with response:
            return response.status, response.read(), response.headers

    def test_dashboard_and_snapshot_have_real_same_origin_routes(self) -> None:
        code, body, _ = self.request("/")
        self.assertEqual(code, 200)
        self.assertIn(b"/dashboard/app.js", body)
        code, body, _ = self.request("/api/snapshot")
        self.assertEqual(code, 200)
        snapshot = json.loads(body)
        self.assertEqual(
            set(snapshot["health"]["components"]), {"listener", "monitor", "usage", "git", "version", "runtime_data"}
        )
        self.assertIn("usage_refresh", snapshot)
        self.assertEqual(len(self.request("/rainmeter")[1].decode().split("|")), 28)

    def test_lan_data_routes_require_a_configured_token_while_static_dashboard_loads(self) -> None:
        original_setup = service.StatusHandler.setup

        def remote_setup(handler: service.StatusHandler) -> None:
            original_setup(handler)
            handler.client_address = ("192.0.2.10", handler.client_address[1])

        with patch.object(service.StatusHandler, "setup", remote_setup):
            with patch.object(service, "STATUS_ACCESS_TOKEN", ""):
                self.assertEqual(self.request("/")[0], 200)
                for route in ("/status", "/health", "/usage", "/tasks", "/rainmeter", "/api/snapshot", "/api/history"):
                    with self.subTest(route=route), patch.object(service, "dashboard_snapshot") as snapshot:
                        code, body, _ = self.request(route)
                        self.assertEqual(code, 403)
                        self.assertIn("令牌", json.loads(body)["error"])
                        snapshot.assert_not_called()
            with patch.object(service, "STATUS_ACCESS_TOKEN", "private-test-token"):
                self.assertEqual(self.request("/health")[0], 403)
                self.assertEqual(self.request("/health?token=wrong")[0], 403)
                code, body, _ = self.request("/rainmeter?token=private-test-token")
                self.assertEqual(code, 200)
                self.assertEqual(len(body.decode().split("|")), 28)
                self.assertEqual(
                    self.request("/api/snapshot", headers={"Authorization": "Bearer private-test-token"})[0], 200
                )

    def test_manual_refresh_is_nonblocking_and_foreign_origin_is_rejected(self) -> None:
        with patch.object(service.usage_refresh_worker, "request", return_value=True) as refresh:
            code, _, _ = self.request(
                "/api/usage/refresh", method="POST", data={}, headers={"Origin": "https://example.invalid"}
            )
            self.assertEqual(code, 403)
            refresh.assert_not_called()
            code, body, _ = self.request("/api/usage/refresh", method="POST", data={})
            self.assertEqual(code, 202)
            self.assertTrue(json.loads(body)["started"])
            refresh.assert_called_once()

    def test_cors_preflight_has_bearer_and_json_headers(self) -> None:
        with patch.object(service, "ALLOW_CORS", True):
            code, _, headers = self.request("/api/snapshot", method="OPTIONS")
        self.assertEqual(code, 204)
        self.assertIn("Authorization", headers["Access-Control-Allow-Headers"])
        self.assertIn("POST", headers["Access-Control-Allow-Methods"])

    def test_invalid_input_returns_json_without_mutation(self) -> None:
        code, body, _ = self.request("/api/tasks/control", method="POST", data=[])
        self.assertEqual(code, 400)
        self.assertIn("error", json.loads(body))
        code, _, _ = self.request("/api/history?limit=invalid")
        self.assertEqual(code, 400)
        self.assertEqual(self.request("/unknown")[0], 404)

    def test_peer_credentials_are_never_in_public_response(self) -> None:
        code, _, _ = self.request(
            "/api/peers",
            method="POST",
            data={"action": "add", "name": "另一台电脑", "url": "http://127.0.0.1:12345", "token": "private-secret"},
        )
        self.assertEqual(code, 200)
        code, body, _ = self.request("/api/peers")
        self.assertEqual(code, 200)
        self.assertNotIn(b"private-secret", body)
        self.assertEqual(json.loads(body)["total"], 1)

    def test_task_controls_and_history_are_connected_to_live_telemetry(self) -> None:
        path = Path(self.folder.name) / "rollout-test.jsonl"
        events = [
            {
                "timestamp": "2026-10-03T01:00:00Z",
                "type": "session_meta",
                "payload": {"id": "session-one", "cwd": str(Path(self.folder.name) / "工程A")},
            },
            {
                "timestamp": "2026-10-03T01:00:01Z",
                "type": "event_msg",
                "payload": {"type": "task_started", "turn_id": "turn-one"},
            },
        ]
        path.write_text("".join(json.dumps(item) + "\n" for item in events))
        service.TELEMETRY.rebuild([path])
        for action in ("select", "pin"):
            code, _, _ = self.request(
                "/api/tasks/control",
                method="POST",
                data={"action": action, "session_id": "session-one", "turn_id": "turn-one"},
            )
            self.assertEqual(code, 200)
        snapshot = json.loads(self.request("/api/snapshot")[1])
        self.assertEqual(snapshot["task"]["pinned_session_id"], "session-one")
        code, body, _ = self.request("/api/history?status=running&limit=1")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["total"], 1)
        code, _, _ = self.request(
            "/api/tasks/control",
            method="POST",
            data={"action": "ignore", "session_id": "session-one", "turn_id": "turn-one"},
        )
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(self.request("/api/snapshot")[1])["task"]["active_count"], 0)
        self.assertTrue(path.exists())
        code, _, _ = self.request(
            "/api/tasks/control",
            method="POST",
            data={"action": "recheck", "session_id": "session-one", "turn_id": "turn-one"},
        )
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(self.request("/api/snapshot")[1])["task"]["active_count"], 0)
        code, _, _ = self.request(
            "/api/tasks/control",
            method="POST",
            data={"action": "select", "session_id": "session-one", "turn_id": "turn-one"},
        )
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(self.request("/api/snapshot")[1])["task"]["active_count"], 1)

    @unittest.skipIf(sys.platform == "win32", "POSIX TIME_WAIT regression")
    def test_served_port_can_be_rebound_immediately_but_not_shared(self) -> None:
        self.request("/usage")
        with self.assertRaises(OSError):
            service.StatusServer(("127.0.0.1", self.port), service.StatusHandler)
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        replacement = service.StatusServer(("127.0.0.1", self.port), service.StatusHandler)
        replacement.server_close()


if __name__ == "__main__":
    unittest.main()
