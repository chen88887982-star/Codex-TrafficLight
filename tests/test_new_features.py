from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from codex_status_server import build_tasks_payload, service_health_snapshot
from codex_telemetry import CodexTelemetry
from git_runtime import classify_git_error, git_environment, git_retry_delay
from notifications import NotificationManager, in_quiet_hours
from service_metadata import RAINMETER_PROTOCOL_VERSION, SERVICE_NAME, SERVICE_VERSION
from service_runtime import IntervalScheduler, RotatingTextLog


class NewFeatureTests(unittest.TestCase):
    def test_health_exposes_service_and_protocol_versions(self) -> None:
        with (
            patch("codex_status_server.TELEMETRY.runtime_health", return_value={}),
            patch("codex_status_server.usage_refresh_worker.snapshot", return_value={}),
        ):
            health = service_health_snapshot(task_data={"event_age_seconds": 0, "git_remote_status": "disabled"})
        self.assertEqual(health["service"], SERVICE_NAME)
        self.assertEqual(health["service_version"], SERVICE_VERSION)
        self.assertEqual(health["protocol_version"], RAINMETER_PROTOCOL_VERSION)

    def test_version_is_consistent_across_service_skin_and_launchers(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.assertIn(f'version = "{SERVICE_VERSION}"', (root / "pyproject.toml").read_text(encoding="utf-8"))
        skin = (root / "rainmeter" / "CodexTrafficLight" / "CodexTrafficLight.ini").read_text(encoding="utf-16")
        self.assertIn(f"Version={SERVICE_VERSION}", skin)
        for launcher in (
            root / "win" / "codex_status_server" / ".internal" / "start-server-background.ps1",
            root / "mac" / "codex_status_server" / ".internal" / "start-background.command",
        ):
            self.assertIn(SERVICE_VERSION, launcher.read_text(encoding="utf-8-sig"))

    def test_tasks_payload_keeps_a_fixed_five_row_contract(self) -> None:
        payload = build_tasks_payload(
            {
                "active_tasks": [
                    {
                        "project": "project|one",
                        "task_title": "实现功能",
                        "stage": "正在测试",
                        "elapsed_seconds": 65,
                    }
                ]
            }
        )
        fields = payload.split("|")
        self.assertEqual(len(fields), 21)
        self.assertEqual(fields[:5], ["1", "project/one", "实现功能", "正在测试", "01:05"])

    def test_git_network_environment_is_fully_noninteractive(self) -> None:
        environment = git_environment(network=True)
        self.assertEqual(environment["GIT_TERMINAL_PROMPT"], "0")
        self.assertEqual(environment["GCM_INTERACTIVE"], "Never")
        self.assertEqual(classify_git_error("TLS connection timed out"), "网络失败")
        self.assertEqual(git_retry_delay(99), 300)

    def test_interval_scheduler_can_be_disabled_and_rearms(self) -> None:
        disabled = IntervalScheduler(0, now=10)
        self.assertFalse(disabled.due(now=100))
        scheduler = IntervalScheduler(30, now=10)
        self.assertFalse(scheduler.due(now=39))
        self.assertTrue(scheduler.due(now=40))
        self.assertFalse(scheduler.due(now=69))
        self.assertTrue(scheduler.due(now=70))

    def test_rotating_log_removes_oversized_and_excess_legacy_backups(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "status-server.log"
            path.with_name("status-server.log.1").write_bytes(b"x" * 2048)
            path.with_name("status-server.log.4").write_bytes(b"x")
            RotatingTextLog(path, max_bytes=1024, backups=3)
            self.assertFalse(path.with_name("status-server.log.1").exists())
            self.assertFalse(path.with_name("status-server.log.4").exists())

    def test_error_state_expires_after_configured_hold(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            telemetry = CodexTelemetry(Path(temporary))
            task_path = Path(temporary) / "rollout-12345678-1234-1234-1234-123456789abc.jsonl"
            task = telemetry.task_for(task_path)
            task.session_id = "12345678-1234-1234-1234-123456789abc"
            task.status = "error"
            task.updated_at = 1
            task.completed_at = 1
            self.assertTrue(telemetry.expire_errors(0))
            self.assertEqual(task.status, "idle")

    def test_notifications_honor_quiet_hours_and_deduplicate(self) -> None:
        self.assertTrue(in_quiet_hours("22:00-08:00", datetime(2026, 1, 1, 23, 0)))
        self.assertFalse(in_quiet_hours("22:00-08:00", datetime(2026, 1, 1, 12, 0)))
        manager = NotificationManager(enabled=True)
        with patch("notifications.threading.Thread") as thread:
            self.assertTrue(manager.notify("waiting", "turn-1", "project"))
            self.assertFalse(manager.notify("waiting", "turn-1", "project"))
        thread.assert_called_once()


if __name__ == "__main__":
    unittest.main()
