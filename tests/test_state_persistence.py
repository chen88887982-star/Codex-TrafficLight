from __future__ import annotations

import json
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import codex_status_server as service
from state_store import JsonObjectStore


class StatePersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / "usage-cache.json"
        self.status_path = Path(self.folder.name) / "status.json"
        self.store = JsonObjectStore()
        self.cached = {
            **service.DEFAULT_USAGE,
            "source": "app_server",
            "available": True,
            "primary_used_percent": 20,
            "primary_remaining_value": 80,
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        self.path.write_text(json.dumps(self.cached), encoding="utf-8")
        self.patches = [
            patch.object(service, "USAGE_CACHE_FILE", self.path),
            patch.object(service, "STATUS_FILE", self.status_path),
            patch.object(service, "state_store", self.store),
            patch.object(service, "write_log"),
            patch.dict(
                service.usage_query_health,
                {"last_success_at": 1.0, "last_error": "", "last_error_at": 0.0},
                clear=True,
            ),
        ]
        for item in self.patches:
            item.start()
        service.read_usage_cache()

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        self.folder.cleanup()

    def test_status_write_failure_preserves_old_state_until_successful_write(self) -> None:
        service.write_status("running", "正在工作")
        with patch.object(service, "atomic_write_json", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                service.write_status("success", "任务完成")
        for _ in range(3):
            self.assertEqual(service.read_status()["status"], "running")
            self.assertTrue(self.store.errors())
        service.write_status("success", "任务完成")
        self.assertEqual(service.read_status()["status"], "success")
        self.assertFalse(self.store.errors())

    def test_failed_live_cache_write_retains_old_data_and_reports_failure(self) -> None:
        queried = {**self.cached, "primary_used_percent": 30, "primary_remaining_value": 70}
        with (
            patch.object(service, "query_live_account_usage", return_value=queried),
            patch.object(service, "atomic_write_json", side_effect=OSError("disk full")),
            patch.object(service, "latest_session_usage_fallback", return_value=None),
        ):
            result = service.refresh_usage_cache_once()

        self.assertEqual(result["primary_remaining_value"], 80)
        self.assertEqual(service.usage_query_health["last_success_at"], 1.0)
        self.assertIn("OSError", service.usage_query_health["last_error"])
        self.assertGreater(service.usage_query_health["last_error_at"], 0)
        self.assertTrue(self.store.errors())
        for _ in range(3):
            self.assertEqual(service.read_usage_cache()["primary_remaining_value"], 80)
            self.assertTrue(self.store.errors())
        with patch.object(service, "AUTO_MONITOR", False):
            health = service.service_health_snapshot(service.read_usage_cache())
        self.assertEqual(health["status"], "degraded")
        self.assertEqual(health["components"]["runtime_data"]["status"], "degraded")

    def test_successful_write_is_required_to_clear_persistence_error(self) -> None:
        queried = {**self.cached, "primary_used_percent": 30, "primary_remaining_value": 70}
        with patch.object(service, "atomic_write_json", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                service.write_usage_cache(queried)
        self.assertTrue(self.store.errors())
        service.read_usage_cache()
        self.assertTrue(self.store.errors())

        with patch.object(service, "query_live_account_usage", return_value=queried):
            recovered = service.refresh_usage_cache_once()
        self.assertEqual(recovered["primary_remaining_value"], 70)
        self.assertFalse(self.store.errors())
        self.assertEqual(service.usage_query_health["last_error"], "")
        self.assertGreater(service.usage_query_health["last_success_at"], 1.0)

    def test_failed_session_fallback_does_not_interrupt_event_processing(self) -> None:
        event = {
            "type": "event_msg",
            "timestamp": datetime.fromtimestamp(time.time() + 2).astimezone().isoformat(),
            "payload": {
                "type": "token_count",
                "rate_limits": {"primary": {"used_percent": 30}},
            },
        }
        with (
            patch.dict(service.usage_query_health, {"last_error": "live query unavailable"}),
            patch.object(service, "atomic_write_json", side_effect=OSError("disk full")),
        ):
            self.assertIsNone(service.consider_session_usage_fallback(event, Path(self.folder.name) / "rollout.jsonl"))
        self.assertEqual(service.read_usage_cache()["primary_remaining_value"], 80)
        self.assertTrue(self.store.errors())

    def test_failed_live_query_and_fallback_write_both_keep_old_cache(self) -> None:
        with (
            patch.object(service, "query_live_account_usage", side_effect=TimeoutError("offline")),
            patch.object(service, "latest_session_usage_fallback", side_effect=OSError("disk full")),
        ):
            result = service.refresh_usage_cache_once()
        self.assertEqual(result["primary_remaining_value"], 80)
        self.assertIn("TimeoutError", service.usage_query_health["last_error"])
        self.assertEqual(service.usage_query_health["last_success_at"], 1.0)


if __name__ == "__main__":
    unittest.main()
