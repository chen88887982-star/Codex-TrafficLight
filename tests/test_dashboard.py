from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError
from urllib.request import ProxyHandler

from dashboard import dashboard_asset
from peer_services import (
    MAX_RESPONSE_BYTES,
    PeerFetchError,
    PeerServiceManager,
    _fetch_peer_snapshot_in_worker,
    _NoRedirect,
    fetch_peer_snapshot,
    validate_service_url,
)


def sample_snapshot(title: str = "实现任务") -> dict[str, object]:
    return {
        "status": {"status": "running"},
        "usage": {"available": True, "primary_remaining_value": 70},
        "task": {"task_title": title, "active_count": 1},
        "health": {"status": "ok"},
    }


class DashboardAssetTests(unittest.TestCase):
    def test_assets_only_resolve_explicit_routes(self) -> None:
        for path, content_type in (
            ("/", "text/html"),
            ("/dashboard/", "text/html"),
            ("/dashboard/app.js", "application/javascript"),
            ("/dashboard/style.css", "text/css"),
        ):
            asset = dashboard_asset(path)
            self.assertIsNotNone(asset)
            self.assertTrue(asset[1].startswith(content_type))
            self.assertGreater(len(asset[0]), 200)
        for path in (
            "/dashboard/../status-auth.json",
            "/dashboard/%2e%2e/README.md",
            "/etc/passwd",
            "/dashboard/index.html",
        ):
            self.assertIsNone(dashboard_asset(path))

    def test_dashboard_supports_mobile_access_and_safe_text(self) -> None:
        html = dashboard_asset("/dashboard")[0].decode("utf-8")
        javascript = dashboard_asset("/dashboard/app.js")[0].decode("utf-8")
        self.assertIn('name="viewport"', html)
        self.assertIn('type="password"', html)
        self.assertIn("sessionStorage", javascript)
        self.assertNotIn("innerHTML", javascript)
        self.assertNotIn("insertAdjacentHTML", javascript)


class PeerServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / ".runtime" / "peers.json"
        self.manager = PeerServiceManager(self.path, max_peers=2, timeout=0.1)

    def tearDown(self) -> None:
        self.manager.stop()
        self.temporary.cleanup()

    def test_validate_url_rejects_credentials_queries_and_non_http(self) -> None:
        for url in (
            "file:///etc/passwd",
            "ftp://device",
            "http://secret@device",
            "http://device/?token=abc",
            "http://device/a",
            "http://device/#x",
            "http://device:70000",
            "http://device\n.example",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_service_url(url)
        self.assertEqual(validate_service_url(" HTTP://127.0.0.1:8767/ "), "http://127.0.0.1:8767")
        self.assertEqual(validate_service_url("http://[::1]:8767/"), "http://[::1]:8767")

    def test_private_config_round_trip_and_no_token_in_public_response(self) -> None:
        result = self.manager.control("add", name="工作室", url="http://device:8767", token="private-test-token")
        snapshot = self.manager.public_snapshot()
        self.assertEqual(snapshot["items"][0]["id"], result["peer_id"])
        self.assertNotIn("private-test-token", json.dumps(snapshot))
        self.assertFalse(snapshot["items"][0]["connected"])
        loaded = PeerServiceManager(self.path)
        self.assertEqual(loaded.public_snapshot()["total"], 1)
        if os.name != "nt":
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.manager.control("remove", peer_id=result["peer_id"])
        self.assertEqual(PeerServiceManager(self.path).public_snapshot()["total"], 0)

    def test_bounded_count_and_duplicate_url_updates_existing_device(self) -> None:
        first = self.manager.control("add", name="设备 1", url="http://first")
        self.manager.control("add", name="设备 2", url="http://second")
        with self.assertRaises(ValueError):
            self.manager.control("add", name="设备 3", url="http://third")
        updated = self.manager.control("add", name="重新命名", url="http://first/")
        self.assertEqual(first["peer_id"], updated["peer_id"])
        self.assertEqual(self.manager.public_snapshot()["items"][0]["name"], "重新命名")

    def test_failed_poll_retains_last_snapshot_and_marks_it_stale(self) -> None:
        result = self.manager.control("add", name="设备", url="http://device")
        peer = self.manager._peers[result["peer_id"]].copy()
        with patch("peer_services.fetch_peer_snapshot", return_value=sample_snapshot()):
            self.manager._poll(peer)
        first = self.manager.public_snapshot()["items"][0]
        self.assertTrue(first["connected"])
        with patch("peer_services.fetch_peer_snapshot", side_effect=PeerFetchError("服务离线")):
            self.manager._poll(peer)
        last = self.manager.public_snapshot()["items"][0]
        self.assertTrue(last["stale"])
        self.assertFalse(last["connected"])
        self.assertEqual(last["snapshot"], first["snapshot"])
        self.assertEqual(last["last_success_at"], first["last_success_at"])
        last["snapshot"]["task"]["task_title"] = "不能修改内部缓存"
        self.assertEqual(self.manager.public_snapshot()["items"][0]["snapshot"]["task"]["task_title"], "实现任务")

    def test_public_read_does_not_wait_for_remote_poll(self) -> None:
        self.manager.control("add", name="设备", url="http://device")
        entered = threading.Event()
        release = threading.Event()

        def blocked_fetch(*args, **kwargs):
            entered.set()
            release.wait(2)
            return sample_snapshot()

        with patch("peer_services.fetch_peer_snapshot", side_effect=blocked_fetch):
            self.manager.start()
            try:
                self.assertTrue(entered.wait(1))
                started = time.monotonic()
                self.assertEqual(self.manager.public_snapshot()["total"], 1)
                self.assertLess(time.monotonic() - started, 0.2)
            finally:
                release.set()
                self.manager.stop()
        self.assertFalse(self.manager._thread.is_alive())

    def test_deleted_or_reconfigured_peer_discards_inflight_response(self) -> None:
        result = self.manager.control("add", name="设备", url="http://device", token="old")
        peer = self.manager._peers[result["peer_id"]].copy()

        def reconfigure_then_return(*args, **kwargs):
            self.manager.control("add", name="设备", url="http://device", token="new")
            return sample_snapshot()

        with patch("peer_services.fetch_peer_snapshot", side_effect=reconfigure_then_return):
            self.manager._poll(peer)
        self.assertIsNone(self.manager.public_snapshot()["items"][0]["snapshot"])
        self.manager.control("remove", peer_id=result["peer_id"])
        with patch("peer_services.fetch_peer_snapshot", return_value=sample_snapshot()):
            self.manager._poll(peer)
        self.assertEqual(self.manager.public_snapshot()["items"], [])

    def test_persistence_failure_rolls_back_mutation(self) -> None:
        with patch.object(self.manager, "_save", side_effect=OSError("disk full")), self.assertRaises(OSError):
            self.manager.control("add", name="设备", url="http://device")
        self.assertEqual(self.manager.public_snapshot()["total"], 0)

    def test_malformed_configuration_is_reported_without_crashing(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_text("[]", encoding="utf-8")
        manager = PeerServiceManager(self.path)
        self.assertEqual(manager.public_snapshot()["items"], [])
        self.assertTrue(manager.public_snapshot()["configuration_error"])

    def test_transport_uses_authorization_header_and_disables_system_proxy(self) -> None:
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value = io.BytesIO(json.dumps(sample_snapshot()).encode())
        with patch("peer_services.build_opener", return_value=opener) as build:
            result = _fetch_peer_snapshot_in_worker("http://device", "a-private-token")
        self.assertEqual(result["task"]["task_title"], "实现任务")
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer a-private-token")
        self.assertNotIn("a-private-token", request.full_url)
        self.assertTrue(
            any(isinstance(handler, ProxyHandler) and not handler.proxies for handler in build.call_args.args)
        )

    def test_transport_rejects_oversized_or_incompatible_responses(self) -> None:
        for body in (b"x" * (MAX_RESPONSE_BYTES + 1), b"[]", b'{"status": "idle"}', b"not-json"):
            opener = MagicMock()
            opener.open.return_value.__enter__.return_value = io.BytesIO(body)
            with (
                self.subTest(size=len(body)),
                patch("peer_services.build_opener", return_value=opener),
                self.assertRaises(PeerFetchError),
            ):
                _fetch_peer_snapshot_in_worker("http://device")

    def test_transport_public_error_never_contains_credentials(self) -> None:
        opener = MagicMock()
        opener.open.side_effect = HTTPError("http://device", 403, "secret-header-value", {}, None)
        with patch("peer_services.build_opener", return_value=opener), self.assertRaises(PeerFetchError) as raised:
            _fetch_peer_snapshot_in_worker("http://device", "secret-header-value")
        self.assertNotIn("secret-header-value", str(raised.exception))
        self.assertIn("访问被拒绝", str(raised.exception))

    def test_redirect_is_rejected_without_forwarding_a_private_token(self) -> None:
        response = MagicMock()
        with self.assertRaises(PeerFetchError):
            _NoRedirect().redirect_request(None, response, 302, "redirect", {}, "http://other-device")
        response.close.assert_called_once()


class PeerDeadlineTests(unittest.TestCase):
    """Use only an ephemeral loopback listener and the actual child transport."""

    def setUp(self) -> None:
        self.mode = "normal"
        self.stopping = threading.Event()
        self.received = threading.Event()
        self.disconnected = threading.Event()
        self.authorization = ""
        self.request_path = ""
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                fixture.authorization = self.headers.get("Authorization", "")
                fixture.request_path = self.path
                fixture.received.set()
                if fixture.mode == "normal":
                    body = json.dumps(sample_snapshot(), ensure_ascii=False).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                try:
                    if fixture.mode == "slow_headers":
                        self.connection.sendall(b"HTTP/1.1 200 OK\r\nX-Progress: ")
                    else:
                        self.connection.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 100000\r\n\r\n")
                    while not fixture.stopping.wait(0.025):
                        self.connection.sendall(b"x")
                except OSError:
                    fixture.disconnected.set()

            def log_message(self, *args) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.stopping.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=1)

    def test_normal_response_uses_token_header_and_ignores_environment_proxy(self) -> None:
        with patch.dict(os.environ, {"http_proxy": "http://127.0.0.1:1", "HTTP_PROXY": "http://127.0.0.1:1"}):
            snapshot = fetch_peer_snapshot(self.url, "deadline-test-token", timeout=2)
        self.assertEqual(snapshot["task"]["task_title"], "实现任务")
        self.assertEqual(self.authorization, "Bearer deadline-test-token")
        self.assertEqual(self.request_path, "/api/snapshot")

    def assert_drip_is_terminated(self, mode: str) -> None:
        self.mode = mode
        created: list[subprocess.Popen] = []
        real_popen = subprocess.Popen

        def record_child(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            created.append(process)
            return process

        started = time.monotonic()
        with (
            patch("peer_services.subprocess.Popen", side_effect=record_child),
            self.assertRaises(PeerFetchError) as raised,
        ):
            fetch_peer_snapshot(self.url, "drip-test-token", timeout=0.6)
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertIn("超时", str(raised.exception))
        self.assertTrue(self.received.is_set(), "The regression must reach the slow HTTP peer")
        self.assertTrue(self.disconnected.wait(1), "The timed-out child must close the real connection")
        self.assertEqual(len(created), 1)
        self.assertIsNotNone(created[0].poll(), "The worker must be reaped rather than abandoned")
        self.assertNotIn("drip-test-token", " ".join(created[0].args))
        self.assertNotIn("drip-test-token", str(raised.exception))

    def test_slow_drip_headers_are_aborted_within_total_deadline(self) -> None:
        self.assert_drip_is_terminated("slow_headers")

    def test_slow_drip_body_is_aborted_within_total_deadline(self) -> None:
        self.assert_drip_is_terminated("slow_body")


if __name__ == "__main__":
    unittest.main()
