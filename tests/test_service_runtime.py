from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from codex_status_server import (
    consider_session_usage_fallback,
    effective_status,
    format_sync_label,
    query_live_account_usage,
    refresh_usage_cache_once,
    remove_pid_file,
    request_authorized,
    service_health_snapshot,
    usage_from_session_rate_limits,
    write_pid_file,
)
from service_runtime import JsonlFollower, RotatingTextLog, SingleFlightWorker, TaskRefreshTracker, atomic_write_json


class ServiceRuntimeTests(unittest.TestCase):
    def test_atomic_json_write_replaces_complete_document(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state.json"
            atomic_write_json(path, {"version": 1})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"version": 1})

            with patch("service_runtime.os.replace", side_effect=OSError("replace failed")):
                with self.assertRaises(OSError):
                    atomic_write_json(path, {"version": 2})

            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"version": 1})
            self.assertEqual(list(path.parent.glob(".state.json.*.tmp")), [])

    def test_rotating_log_bounds_active_file_and_keeps_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "service.log"
            log = RotatingTextLog(path, max_bytes=1024, backups=2)
            log.write("a" * 900)
            log.write("b" * 200)
            self.assertEqual(path.read_text(encoding="utf-8"), "b" * 200 + "\n")
            self.assertTrue(path.with_name("service.log.1").exists())

    def test_jsonl_follower_buffers_partial_lines_and_handles_truncation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "events.jsonl"
            path.write_bytes(b'{"id": 1')
            follower = JsonlFollower()
            self.assertEqual(follower.read_lines(path), [])

            with path.open("ab") as handle:
                handle.write(b'}\n{"id": 2}\n')
            self.assertEqual(follower.read_lines(path), ['{"id": 1}', '{"id": 2}'])

            path.write_text('{"id": 3}\n', encoding="utf-8")
            self.assertEqual(follower.read_lines(path), ['{"id": 3}'])
            path.unlink()
            self.assertEqual(follower.read_lines(path), [])
            self.assertEqual(follower.tracked_count, 0)

    def test_single_flight_worker_coalesces_overlapping_requests(self) -> None:
        started = threading.Event()
        release = threading.Event()
        completed = threading.Event()
        lock = threading.Lock()
        calls = 0
        concurrent = 0
        maximum_concurrent = 0

        def action() -> None:
            nonlocal calls, concurrent, maximum_concurrent
            with lock:
                calls += 1
                concurrent += 1
                maximum_concurrent = max(maximum_concurrent, concurrent)
                current_call = calls
            started.set()
            if current_call == 1:
                release.wait(timeout=2)
            with lock:
                concurrent -= 1
                if calls == 2:
                    completed.set()

        worker = SingleFlightWorker(action, name="test-single-flight")
        self.assertTrue(worker.request())
        self.assertTrue(started.wait(timeout=2))
        self.assertFalse(worker.request())
        self.assertFalse(worker.request())
        release.set()
        self.assertTrue(completed.wait(timeout=2))
        for _ in range(100):
            if not worker.running:
                break
            time.sleep(0.01)
        self.assertEqual(calls, 2)
        self.assertEqual(maximum_concurrent, 1)

    def test_single_flight_worker_reports_background_errors(self) -> None:
        finished = threading.Event()

        def failing_action() -> None:
            finished.set()
            raise RuntimeError("refresh failed")

        worker = SingleFlightWorker(failing_action, name="test-failing-worker")
        worker.request()
        self.assertTrue(finished.wait(timeout=2))
        for _ in range(100):
            if not worker.running:
                break
            time.sleep(0.01)
        self.assertIn("refresh failed", worker.snapshot()["last_error"])

    def test_effective_status_uses_telemetry_after_monitor_initializes(self) -> None:
        with patch.dict("codex_status_server.monitor_health", {"initialized": True}, clear=False):
            result = effective_status(
                {"status": "success", "message": "old", "updated_at": "old"},
                {"status": "running", "stage": "正在测试", "updated_at": "new"},
            )
        self.assertEqual(result["status"], "running")
        self.assertEqual(result["message"], "正在测试")
        self.assertEqual(result["updated_at"], "new")

    def test_health_reports_monitor_heartbeat_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with (
                patch("codex_status_server.CODEX_SESSIONS_DIR", Path(temporary)),
                patch.dict(
                    "codex_status_server.monitor_health",
                    {"initialized": True, "heartbeat_at": time.time() - 60},
                    clear=False,
                ),
            ):
                health = service_health_snapshot({"available": False})
        self.assertEqual(health["status"], "error")
        self.assertFalse(health["ok"])
        self.assertEqual(health["service"], "codex-traffic-light-status")
        self.assertIn("会话监控心跳超时", health["reasons"])

    def test_health_uses_selected_project_git_refresh_state(self) -> None:
        telemetry = {
            "tracked_tasks": 2,
            "git_refreshing": 0,
            "git_last_finished_at": 0.0,
            "git_last_error": "",
            "git_fetching": 0,
            "git_fetch_last_success": 0.0,
            "git_fetch_last_error": "另一个项目凭据失败",
            "git_fetch_unconfirmed": 1,
        }
        with (
            patch("codex_status_server.AUTO_MONITOR", False),
            patch("codex_status_server.TELEMETRY.runtime_health", return_value=telemetry),
        ):
            verified = service_health_snapshot(
                {"available": False}, {"git_remote_status": "verified", "git_remote_error_label": ""}
            )
            unconfirmed = service_health_snapshot(
                {"available": False}, {"git_remote_status": "unconfirmed", "git_remote_error_label": "网络失败"}
            )
        self.assertNotIn("Git 另一个项目凭据失败", verified["reasons"])
        self.assertIn("Git 网络失败", unconfirmed["reasons"])
        self.assertEqual(unconfirmed["status"], "degraded")

    def test_status_token_is_required_only_for_non_loopback_clients(self) -> None:
        with patch("codex_status_server.STATUS_ACCESS_TOKEN", "secret-token"):
            self.assertTrue(request_authorized("127.0.0.1", {}, ""))
            self.assertTrue(request_authorized("::1", {}, ""))
            self.assertFalse(request_authorized("192.168.2.117", {}, ""))
            self.assertTrue(request_authorized("192.168.2.117", {"token": ["secret-token"]}, ""))
            self.assertTrue(request_authorized("192.168.2.117", {}, "Bearer secret-token"))

    def test_pid_file_is_removed_only_by_own_process(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pid_file = Path(temporary) / "status-server.pid"
            with patch("codex_status_server.PID_FILE", pid_file):
                write_pid_file()
                self.assertTrue(pid_file.exists())
                remove_pid_file()
                self.assertFalse(pid_file.exists())

    def test_task_refresh_tracker_refreshes_each_task_once(self) -> None:
        tracker = TaskRefreshTracker()
        task = ("/tmp/session.jsonl", "turn-1")
        tracker.mark_active(task)
        self.assertTrue(tracker.complete(task, success=True))
        self.assertFalse(tracker.complete(task, success=True))

        aborted = ("/tmp/session.jsonl", "turn-2")
        tracker.mark_active(aborted)
        self.assertFalse(tracker.complete(aborted, success=False))

    def test_optional_credits_failure_keeps_valid_rate_limits(self) -> None:
        helper = """
import json, sys
for line in sys.stdin:
    request = json.loads(line)
    request_id = request['id']
    method = request['method']
    if method == 'initialize':
        result = {}
        response = {'id': request_id, 'result': result}
    elif method == 'account/rateLimits/read':
        response = {'id': request_id, 'result': {'rateLimits': {'planType': 'plus', 'primary': {'usedPercent': 25, 'resetsAt': 1893456000}}}}
    else:
        response = {'id': request_id, 'error': {'message': 'credits unavailable'}}
    print(json.dumps(response), flush=True)
"""
        with (
            patch("codex_status_server.resolve_codex_command", return_value=[sys.executable, "-c", helper]),
            patch("codex_status_server.ACCOUNT_QUERY_TIMEOUT_SECONDS", 3),
            patch("codex_status_server.write_log"),
        ):
            usage = query_live_account_usage()
        self.assertTrue(usage["available"])
        self.assertEqual(usage["primary_remaining_value"], 75)
        self.assertFalse(usage["credits_available"])

    def test_failed_live_query_keeps_last_successful_cache(self) -> None:
        cached = {"available": True, "primary_remaining_value": 61, "source": "app_server"}
        with (
            patch("codex_status_server.query_live_account_usage", side_effect=TimeoutError("offline")),
            patch("codex_status_server.read_usage_cache", return_value=cached),
            patch("codex_status_server.latest_session_usage_fallback", return_value=None),
            patch("codex_status_server.write_log"),
        ):
            self.assertIs(refresh_usage_cache_once(), cached)

    def test_failed_live_query_uses_latest_session_fallback(self) -> None:
        fallback = {"available": True, "primary_remaining_value": 57, "source": "session_event"}
        with (
            patch("codex_status_server.query_live_account_usage", side_effect=TimeoutError("offline")),
            patch("codex_status_server.latest_session_usage_fallback", return_value=fallback),
            patch("codex_status_server.write_log"),
        ):
            self.assertIs(refresh_usage_cache_once(), fallback)

    def test_session_rate_limits_are_labeled_as_log_snapshot(self) -> None:
        path = Path("/tmp/session.jsonl")
        event = {
            "timestamp": datetime.now().astimezone().isoformat(),
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "rate_limits": {
                    "plan_type": "plus",
                    "primary": {"used_percent": 43.0, "resets_at": 1893456000},
                    "secondary": None,
                },
            },
        }
        usage = usage_from_session_rate_limits(event, path)
        self.assertIsNotNone(usage)
        assert usage is not None
        self.assertEqual(usage["source"], "session_event")
        self.assertEqual(usage["primary_remaining_value"], 57)
        self.assertTrue(format_sync_label(usage).startswith("日志快照 "))

    def test_fresh_app_server_usage_is_not_replaced_by_session_event(self) -> None:
        event = {
            "timestamp": datetime.now().astimezone().isoformat(),
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "rate_limits": {"primary": {"used_percent": 50, "resets_at": 1893456000}},
            },
        }
        current = {
            "available": True,
            "source": "app_server",
            "updated_at": datetime.now().astimezone().isoformat(),
        }
        with (
            patch("codex_status_server.read_usage_cache", return_value=current),
            patch("codex_status_server.write_usage_cache") as write_cache,
            patch.dict("codex_status_server.usage_query_health", {"last_error": ""}, clear=False),
        ):
            self.assertIsNone(consider_session_usage_fallback(event, Path("/tmp/session.jsonl")))
        write_cache.assert_not_called()


if __name__ == "__main__":
    unittest.main()
