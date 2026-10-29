from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from codex_status_server import parse_usage_window, update_task_usage_snapshot, write_status
from codex_telemetry import CodexTelemetry
from service_doctor import validate_health
from service_metadata import RAINMETER_PROTOCOL_VERSION, SERVICE_NAME, SERVICE_VERSION
from service_runtime import SessionFileIndex

ROOT = Path(__file__).resolve().parents[1]


class AccuracyTests(unittest.TestCase):
    def test_silent_tasks_remain_active_and_recover_on_new_event(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            telemetry = CodexTelemetry(Path(folder))
            for state in ("running", "waiting"):
                task = telemetry.task_for(Path(folder) / f"{state}.jsonl")
                task.session_id = state
                task.status = state
                task.updated_at = time.time() - 600
                task.stage = "原始阶段"
            self.assertTrue(telemetry.expire_stale(300))
            self.assertFalse(telemetry.expire_stale(300))
            self.assertEqual(len(telemetry.active_paths()), 2)
            task = telemetry.task_for(Path(folder) / "waiting.jsonl")
            self.assertEqual(task.status, "waiting")
            self.assertIn("等待用户确认", telemetry._task_summary(task)["stage"])
            telemetry.ingest({"type": "event_msg", "payload": {"type": "agent_reasoning"}}, task.path)
            self.assertFalse(task.stale)
            self.assertEqual(task.status, "running")
            telemetry.ingest({"type": "event_msg", "payload": {"type": "task_complete"}}, task.path)
            self.assertEqual(task.status, "success")

    def test_windows_use_duration_not_slot_and_handle_missing_secondary(self) -> None:
        for minutes, label in ((300, "5小时额度"), (10080, "7天额度"), (15, "15分钟额度")):
            window = parse_usage_window(
                {"usedPercent": 24, "windowDurationMins": minutes, "resetsAt": 2000000000}, "secondary"
            )
            self.assertEqual(window["secondary_window_label"], label)
            self.assertEqual(window["secondary_remaining_value"], 76)
        self.assertIsNone(parse_usage_window(None, "secondary")["secondary_remaining_value"])
        self.assertEqual(parse_usage_window({}, "primary")["primary_window_label"], "主窗口")
        self.assertEqual(
            parse_usage_window({"window_minutes": 300, "used_percent": 30}, "primary", session=True)[
                "primary_window_label"
            ],
            "5小时额度",
        )

    def test_account_delta_survives_status_updates_and_resets_safely(self) -> None:
        with (
            tempfile.TemporaryDirectory() as folder,
            patch("codex_status_server.STATUS_FILE", Path(folder) / "status.json"),
        ):
            path = Path(folder) / "status.json"
            write_status("running", "任务 A")
            usage = {"source": "app_server", "primary_used_percent": 10, "primary_resets_at_epoch": 2000000000}
            update_task_usage_snapshot(usage)
            write_status("running", "任务 B 并行")
            update_task_usage_snapshot({**usage, "primary_used_percent": 13})
            result = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(result["task_usage_primary_label"], "-3%")
            self.assertIn("期间账户变化", result["task_usage_label"])
            for changes in (
                {"primary_used_percent": 1, "primary_resets_at_epoch": 2000100000},
                {"primary_used_percent": 80, "source": "session_event"},
            ):
                update_task_usage_snapshot({**usage, **changes})
                self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["task_usage_primary_label"], "")
            write_status("success", "完成")
            write_status("running", "新任务")
            update_task_usage_snapshot({**usage, "primary_used_percent": 60})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["task_usage_primary_label"], "")

    def test_session_index_avoids_full_walk_until_interval_and_rediscovers_history(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            old = root / "2020/01/01"
            old.mkdir(parents=True)
            first = old / "rollout-old.jsonl"
            first.write_text("")
            index = SessionFileIndex(root, full_scan_seconds=300)
            self.assertEqual(index.recent(now=0), [first])
            today = root / datetime.now().strftime("%Y/%m/%d")
            today.mkdir(parents=True)
            current = today / "rollout-new.jsonl"
            current.write_text("")
            historical = old / "rollout-resumed.jsonl"
            historical.write_text("")
            with patch.object(Path, "rglob", side_effect=AssertionError("unnecessary full scan")):
                self.assertIn(current, index.recent(now=3))
                self.assertNotIn(historical, index.recent(now=6))
            self.assertIn(historical, index.recent(now=300))
            first.unlink()
            self.assertNotIn(first, index.recent(now=303))

    def test_doctor_rejects_old_protocol_wrong_identity_and_errors(self) -> None:
        health = {
            "service": SERVICE_NAME,
            "service_version": SERVICE_VERSION,
            "protocol_version": RAINMETER_PROTOCOL_VERSION,
            "status": "ok",
        }
        self.assertEqual(validate_health(health), [])
        for change in (
            {"protocol_version": 1},
            {"service": "other"},
            {"service_version": "0.3.0"},
            {"status": "error"},
        ):
            self.assertTrue(validate_health({**health, **change}))

    @unittest.skipUnless(sys.platform == "darwin", "macOS launch/stop integration")
    def test_macos_launcher_doctor_duplicate_and_safe_stop(self) -> None:
        # Exercise real scripts in a copied workspace; never touch the user's service.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            shutil.copytree(ROOT / "common", root / "common", ignore=shutil.ignore_patterns("__pycache__"))
            internal = root / "mac/codex_status_server/.internal"
            shutil.copytree(ROOT / "mac/codex_status_server/.internal", internal)
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            env = {**os.environ, "PORT": str(port), "AUTO_MONITOR_CODEX": "0", "PYTHONDONTWRITEBYTECODE": "1"}
            env.pop("CODEX_STATUS_BASE_DIR", None)

            def run(name: str) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    ["bash", str(internal / name)], env=env, capture_output=True, text=True, timeout=30
                )

            try:
                started = run("start-background.command")
                self.assertEqual(started.returncode, 0, started.stdout + started.stderr)
                again = run("start-background.command")
                self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
                self.assertIn("no duplicate", again.stdout)
                checked = run("health-check.command")
                self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
                pid_file = internal.parent / ".runtime/status-server.pid"
                valid = pid_file.read_text()
                pid_file.write_text(json.dumps({"pid": os.getpid()}))
                refused = run("stop.command")
                self.assertNotEqual(refused.returncode, 0)
                pid_file.write_text(valid)
            finally:
                stopped = run("stop.command")
            self.assertEqual(stopped.returncode, 0, stopped.stdout + stopped.stderr)
            self.assertFalse((internal.parent / ".runtime/status-server.pid").exists())
