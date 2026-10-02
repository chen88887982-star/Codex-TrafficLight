from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_telemetry import CodexTelemetry
from task_history import TaskHistory


class TaskHistoryTests(unittest.TestCase):
    def test_new_response_user_format_records_correct_title_for_each_turn(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "rollout-019ffd23-fd68-7952-afc5-78495e834d2e.jsonl"
            tracker = CodexTelemetry(root, history_path=root / "history.sqlite")
            records = []
            for index, title in enumerate(("云端同步", "全部开始优化 升级 开发")):
                turn_id = f"turn-{index}"
                timestamp = 2000000000 + index * 10
                records.extend(
                    [
                        {
                            "timestamp": timestamp,
                            "type": "event_msg",
                            "payload": {"type": "task_started", "turn_id": turn_id},
                        },
                        {
                            "timestamp": timestamp + 1,
                            "type": "response_item",
                            "payload": {
                                "type": "message",
                                "role": "user",
                                "content": [
                                    {
                                        "type": "input_text",
                                        "text": "<environment_context>context</environment_context>",
                                    },
                                    {"type": "input_text", "text": title + "\n"},
                                ],
                            },
                        },
                        {
                            "timestamp": timestamp + 2,
                            "type": "event_msg",
                            "payload": {"type": "task_complete", "turn_id": turn_id},
                        },
                    ]
                )
            path.write_text("\n".join(json.dumps(record) for record in records) + "\n")
            tracker.rebuild([path])
            titles = {item["turn_id"]: item["task_title"] for item in tracker.history_query()["items"]}
            self.assertEqual(titles, {"turn-0": "云端同步", "turn-1": "全部开始优化 升级 开发"})

    def test_running_rebuild_flushes_token_delta_title_and_preserves_git_summary(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "rollout-019ffd23-fd68-7952-afc5-78495e834d2e.jsonl"
            session = "019ffd23-fd68-7952-afc5-78495e834d2e"
            records = [
                {
                    "timestamp": 2000000000,
                    "type": "session_meta",
                    "payload": {"id": session, "cwd": str(root / "项目")},
                },
                {
                    "timestamp": 2000000001,
                    "type": "event_msg",
                    "payload": {"type": "token_count", "info": {"total_token_usage": {"total_tokens": 10000}}},
                },
                {
                    "timestamp": 2000000002,
                    "type": "event_msg",
                    "payload": {"type": "user_message", "message": "完善监控面板"},
                },
                {
                    "timestamp": 2000000003,
                    "type": "event_msg",
                    "payload": {"type": "task_started", "turn_id": "active"},
                },
                {
                    "timestamp": 2000000004,
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {
                            "last_token_usage": {"total_tokens": 9100},
                            "total_token_usage": {"total_tokens": 19100},
                        },
                    },
                },
            ]
            path.write_text("\n".join(json.dumps(record) for record in records) + "\n")
            tracker = CodexTelemetry(root, history_path=root / "history.sqlite")
            tracker.history.record({"session_id": session, "turn_id": "active", "status": "running", "git_added": 99})
            with patch("codex_telemetry.time.monotonic", return_value=100):
                tracker.rebuild([path])
            result = tracker.history_query()["items"][0]
            self.assertEqual(result["tokens"], 9100)
            self.assertEqual(result["last_tokens"], 9100)
            self.assertEqual(result["task_title"], "完善监控面板")
            self.assertEqual(result["git_added"], 99)

    def test_history_initialization_is_lazy_and_existing_git_summary_survives_replay(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / "nested/history.sqlite"
            history = TaskHistory(database)
            self.assertFalse(database.parent.exists())
            history.record({"session_id": "s", "turn_id": "t", "status": "success", "git_added": 12})
            history.record({"session_id": "s", "turn_id": "t", "status": "success", "tokens": 123})
            self.assertEqual(history.query()["items"][0]["git_added"], 12)

    def test_history_write_failures_and_active_throttle_do_not_drop_status(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tracker = CodexTelemetry(root, history_path=root / "history.sqlite")
            path = root / "rollout-019ffd23-fd68-7952-afc5-78495e834d2e.jsonl"
            with patch.object(tracker.history, "record", side_effect=OSError("unwritable")):
                tracker.ingest({"type": "event_msg", "payload": {"type": "task_started", "turn_id": "t1"}}, path)
            self.assertEqual(tracker.task_for(path).status, "running")
            self.assertIn("unwritable", tracker.runtime_health()["history_last_error"])
            with patch.object(tracker.history, "record") as record:
                tracker._persist_history(tracker.task_for(path))
                for _ in range(20):
                    tracker.ingest({"type": "event_msg", "payload": {"type": "token_count", "info": {}}}, path)
                self.assertEqual(record.call_count, 1)
                tracker.ingest({"type": "event_msg", "payload": {"type": "task_complete", "turn_id": "t1"}}, path)
                self.assertEqual(record.call_count, 2)
            self.assertEqual(tracker.task_for(path).status, "success")

    def test_history_filters_paginates_upserts_and_exports_safe_csv(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            history = TaskHistory(Path(folder) / "history.sqlite")
            for index in range(4):
                history.record(
                    {
                        "session_id": "s",
                        "turn_id": str(index),
                        "project": "项目 A" if index < 3 else "项目 B",
                        "task_title": "=danger",
                        "status": "success" if index % 2 else "error",
                        "started_at": 100 + index,
                        "updated_at": 110 + index,
                        "tokens": index * 100,
                    }
                )
            filtered = history.query(project="项目 A", status="error", since=100, until=102, limit=1)
            self.assertEqual(filtered["total"], 2)
            self.assertEqual(filtered["items"][0]["turn_id"], "2")
            self.assertEqual(
                history.query(project="项目 A", status="error", limit=1, offset=1)["items"][0]["turn_id"], "0"
            )
            history.record(
                {
                    "session_id": "s",
                    "turn_id": "2",
                    "project": "项目 A",
                    "status": "success",
                    "started_at": 102,
                    "updated_at": 120,
                    "tokens": 222,
                }
            )
            self.assertEqual(history.query()["total"], 4)
            self.assertEqual(history.query(project="项目 A", status="error")["total"], 1)
            self.assertIn("'=danger", history.export_csv())
            self.assertNotIn("cwd", history.FIELDS)
            self.assertNotIn("prompt", history.FIELDS)

    def test_each_turn_records_token_delta_and_git_summary_without_user_text(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tracker = CodexTelemetry(root, history_path=root / "history.sqlite")
            path = root / "rollout-019ffd23-fd68-7952-afc5-78495e834d2e.jsonl"
            task = tracker.task_for(path)
            task.cwd = str(root / "项目")
            task.total_tokens = 1000
            tracker.ingest(
                {
                    "type": "event_msg",
                    "timestamp": 100,
                    "payload": {"type": "user_message", "message": "private full prompt" + " confidential" * 20},
                },
                path,
            )
            tracker.ingest(
                {"type": "event_msg", "timestamp": 101, "payload": {"type": "task_started", "turn_id": "t1"}}, path
            )
            tracker.ingest(
                {
                    "type": "event_msg",
                    "timestamp": 102,
                    "payload": {
                        "type": "token_count",
                        "info": {
                            "total_token_usage": {"total_tokens": 1500},
                            "last_token_usage": {"total_tokens": 200},
                        },
                    },
                },
                path,
            )
            tracker._persist_history(task, git_stats={"git_files": 2, "git_added": 10})
            tracker.ingest(
                {"type": "event_msg", "timestamp": 106, "payload": {"type": "task_complete", "turn_id": "t1"}}, path
            )
            tracker.ingest(
                {"type": "event_msg", "timestamp": 110, "payload": {"type": "task_started", "turn_id": "t2"}}, path
            )
            tracker.ingest(
                {"type": "event_msg", "timestamp": 113, "payload": {"type": "turn_aborted", "turn_id": "t2"}}, path
            )
            result = tracker.history_query()
            self.assertEqual(result["total"], 2)
            first = next(item for item in result["items"] if item["turn_id"] == "t1")
            self.assertEqual(first["tokens"], 500)
            self.assertEqual(first["duration_seconds"], 5)
            self.assertEqual(first["git_added"], 10)
            self.assertEqual(result["items"][0]["status"], "error")
            self.assertNotIn("private full prompt" + " confidential" * 20, json.dumps(result))
            self.assertLessEqual(len(first["task_title"]), 72)
            self.assertNotIn(str(root), json.dumps(result))

    def test_terminal_history_retention_preserves_active_turns(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            history = TaskHistory(Path(folder) / "history.sqlite", retention_days=1)
            history.record({"session_id": "s", "turn_id": "old", "status": "success", "updated_at": 100})
            history.record({"session_id": "s", "turn_id": "active", "status": "running", "updated_at": 100})
            history.record({"session_id": "s", "turn_id": "new", "status": "success", "updated_at": 100000})
            self.assertEqual({item["turn_id"] for item in history.query()["items"]}, {"active", "new"})


if __name__ == "__main__":
    unittest.main()
