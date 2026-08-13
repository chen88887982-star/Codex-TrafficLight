from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_status_server import extract_credits_label, resolve_codex_command, resolve_expose_task_details
from codex_telemetry import CodexTelemetry, count_unified_diff, friendly_tool_stage


def event(timestamp: str, payload_type: str, **payload: object) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {"type": payload_type, **payload},
    }


class CodexTelemetryTests(unittest.TestCase):
    def test_codex_command_uses_path_when_no_override_is_set(self) -> None:
        with (
            patch("codex_status_server.CODEX_COMMAND", ""),
            patch("codex_status_server.shutil.which", return_value="/opt/codex/bin/codex"),
        ):
            self.assertEqual(resolve_codex_command(), ["/opt/codex/bin/codex"])

    def test_task_details_are_visible_by_default_without_token(self) -> None:
        self.assertTrue(resolve_expose_task_details({}, {}))
        self.assertTrue(resolve_expose_task_details({"access_token": ""}, {}))
        self.assertFalse(resolve_expose_task_details({}, {"EXPOSE_TASK_DETAILS": "0"}))

    def test_counts_patch_lines_without_headers(self) -> None:
        diff = "@@ -1,2 +1,3 @@\n-old\n+new\n+extra\n context\n"
        self.assertEqual(count_unified_diff(diff), (2, 1))

    def test_friendly_tool_stages_hide_internal_names(self) -> None:
        self.assertEqual(friendly_tool_stage("functions.exec_command"), "正在运行命令")
        self.assertEqual(friendly_tool_stage("apply_patch"), "正在修改代码")
        self.assertEqual(friendly_tool_stage("web__run"), "正在查询资料")

    def test_optional_credits_schema_is_conservative(self) -> None:
        self.assertEqual(extract_credits_label({"usage": {"credits": {"balance": 12.5}}}), "12.5")
        self.assertEqual(extract_credits_label({"totalTokens": 1234}), "")

    def test_tracks_multiple_sessions_and_task_complete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tracker = CodexTelemetry(root)
            first = root / "rollout-019ffd23-fd68-7952-afc5-78495e834d2e.jsonl"
            second = root / "rollout-019ffd18-a03f-7cd2-a003-9521a17e3090.jsonl"
            tracker.ingest(
                {
                    "timestamp": "2026-08-14T01:00:00Z",
                    "type": "session_meta",
                    "payload": {"id": "019ffd23-fd68-7952-afc5-78495e834d2e", "cwd": str(root / "one")},
                },
                first,
            )
            tracker.ingest(
                {
                    "timestamp": "2026-08-14T01:00:01Z",
                    "type": "session_meta",
                    "payload": {"id": "019ffd18-a03f-7cd2-a003-9521a17e3090", "cwd": str(root / "two")},
                },
                second,
            )
            tracker.ingest(
                event("2026-08-14T01:00:02Z", "task_started", turn_id="turn-one", started_at=1786669202), first
            )
            tracker.ingest(
                event("2026-08-14T01:00:03Z", "task_started", turn_id="turn-two", started_at=1786669203), second
            )
            snapshot = tracker.snapshot()
            self.assertEqual(snapshot["active_count"], 2)
            self.assertEqual(snapshot["other_active_count"], 1)
            self.assertEqual(snapshot["project"], "two")
            self.assertEqual(snapshot["other_active_project"], "one")

            tracker.ingest(event("2026-08-14T01:00:05Z", "task_complete", turn_id="turn-two", duration_ms=2000), second)
            snapshot = tracker.snapshot()
            self.assertEqual(snapshot["active_count"], 1)
            self.assertEqual(snapshot["project"], "one")

    def test_rebuild_restores_running_task(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session_id = "019ffd23-fd68-7952-afc5-78495e834d2e"
            session = root / f"rollout-{session_id}.jsonl"
            records = [
                {
                    "timestamp": "2026-08-14T01:00:00Z",
                    "type": "session_meta",
                    "payload": {"id": session_id, "cwd": str(root / "project")},
                },
                event("2026-08-14T01:00:01Z", "task_started", turn_id="turn", started_at=1786669201),
                {"timestamp": "2026-08-14T01:00:02Z", "type": "response_item", "payload": {"type": "reasoning"}},
            ]
            session.write_text("\n".join(json.dumps(item) for item in records) + "\n", encoding="utf-8")
            tracker = CodexTelemetry(root)
            tracker.rebuild([session])
            snapshot = tracker.snapshot()
            self.assertEqual(snapshot["status"], "running")
            self.assertEqual(snapshot["project"], "project")

    def test_privacy_snapshot_redacts_work_details(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tracker = CodexTelemetry(root)
            path = root / "rollout-019ffd23-fd68-7952-afc5-78495e834d2e.jsonl"
            tracker.ingest(
                {
                    "timestamp": "2026-08-14T01:00:00Z",
                    "type": "session_meta",
                    "payload": {"id": "019ffd23-fd68-7952-afc5-78495e834d2e", "cwd": str(root / "secret-project")},
                },
                path,
            )
            tracker.ingest(event("2026-08-14T01:00:01Z", "task_started", turn_id="turn", started_at=1786669201), path)
            snapshot = tracker.public_snapshot()
            self.assertEqual(snapshot["project"], "Codex")
            self.assertNotIn("secret-project", json.dumps(snapshot))
            self.assertEqual(snapshot["session_id"], "")

    def test_git_stats_compare_against_task_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            source = root / "app.py"
            source.write_text("print('one')\n", encoding="utf-8")
            subprocess.run(["git", "add", "app.py"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "baseline"], cwd=root, check=True)
            baseline = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
            source.write_text("print('one')\nprint('two')\n", encoding="utf-8")

            tracker = CodexTelemetry(root, git_cache_seconds=0)
            session_id = "019ffd23-fd68-7952-afc5-78495e834d2e"
            path = root / f"rollout-{session_id}.jsonl"
            task = tracker.task_for(path)
            task.session_id = session_id
            task.cwd = str(root)
            task.git_sha = baseline
            task.status = "running"
            task.updated_at = 1786669201
            snapshot = tracker.snapshot()
            self.assertEqual(snapshot["git_files"], 1)
            self.assertEqual(snapshot["git_added"], 1)
            self.assertEqual(snapshot["git_deleted"], 0)
            self.assertTrue(snapshot["git_dirty"])
            self.assertEqual(snapshot["git_change_label"], "当前 1 项  +1  -0")
            self.assertEqual(snapshot["git_cumulative_label"], "本轮 1 项  +1  -0")

            subprocess.run(["git", "add", "app.py"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "task change"], cwd=root, check=True)
            snapshot = tracker.snapshot()
            self.assertEqual(snapshot["git_change_label"], "当前无修改")
            self.assertEqual(snapshot["git_cumulative_label"], "本轮 1 项  +1  -0")
            self.assertEqual(snapshot["git_state_label"], "云端 未跟踪")


if __name__ == "__main__":
    unittest.main()
