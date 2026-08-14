from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_status_server import (
    extract_credits_label,
    read_env_bool,
    read_env_choice,
    read_env_float,
    read_env_int,
    resolve_codex_command,
    resolve_expose_task_details,
)
from codex_telemetry import CodexTelemetry, count_unified_diff, friendly_tool_stage


def event(timestamp: str, payload_type: str, **payload: object) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {"type": payload_type, **payload},
    }


class CodexTelemetryTests(unittest.TestCase):
    def test_invalid_environment_parameters_fall_back_to_safe_defaults(self) -> None:
        with patch.dict(
            "codex_status_server.os.environ",
            {"TEST_INT": "0", "TEST_FLOAT": "nan", "TEST_BOOL": "maybe", "TEST_CHOICE": "unknown"},
            clear=False,
        ):
            self.assertEqual(read_env_int("TEST_INT", 10, 1, 20), 10)
            self.assertEqual(read_env_float("TEST_FLOAT", 2.5, 0.1, 10), 2.5)
            self.assertTrue(read_env_bool("TEST_BOOL", True))
            self.assertEqual(read_env_choice("TEST_CHOICE", "task", {"task", "turn"}), "task")

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
            subprocess.run(["git", "remote", "add", "origin", str(root / "remote.git")], cwd=root, check=True)
            subprocess.run(["git", "update-ref", "refs/remotes/origin/main", baseline], cwd=root, check=True)
            subprocess.run(["git", "branch", "--set-upstream-to=origin/main"], cwd=root, check=True)
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
            self.assertEqual(snapshot["git_change_label"], "本次 1 项  +1  -0")
            self.assertEqual(snapshot["git_cumulative_label"], "待同步 1 项  +1  -0")
            self.assertEqual(snapshot["git_task_label"], "本次 1 项  +1  -0")
            self.assertEqual(snapshot["git_sync_label"], "待同步 1 项  +1  -0")
            self.assertEqual(snapshot["git_sync_files"], 1)

            subprocess.run(["git", "add", "app.py"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "task change"], cwd=root, check=True)
            snapshot = tracker.snapshot()
            self.assertEqual(snapshot["git_change_label"], "本次 1 项  +1  -0")
            self.assertEqual(snapshot["git_cumulative_label"], "待同步 1 项  +1  -0")
            self.assertEqual(snapshot["git_state_label"], "云端 领先 1")

            head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
            subprocess.run(["git", "update-ref", "refs/remotes/origin/main", head], cwd=root, check=True)
            snapshot = tracker.snapshot()
            self.assertEqual(snapshot["git_change_label"], "本次 1 项  +1  -0")
            self.assertEqual(snapshot["git_cumulative_label"], "待同步 0 项  +0  -0")
            self.assertEqual(snapshot["git_state_label"], "云端 已同步")

    def test_git_stats_ignore_excluded_and_mode_only_files_by_default(self) -> None:
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
            source.chmod(0o755)
            if not subprocess.check_output(["git", "status", "--short"], cwd=root, text=True).strip():
                self.skipTest("filesystem does not expose executable-bit changes to Git")
            (root / ".DS_Store").write_bytes(b"metadata")

            tracker = CodexTelemetry(root, git_cache_seconds=0, git_exclude_patterns=(".DS_Store",))
            task = tracker.task_for(root / "rollout-019ffd23-fd68-7952-afc5-78495e834d2e.jsonl")
            task.session_id = "019ffd23-fd68-7952-afc5-78495e834d2e"
            task.cwd = str(root)
            task.git_sha = baseline
            task.status = "running"
            task.updated_at = 1786669201
            snapshot = tracker.snapshot()
            self.assertEqual(snapshot["git_change_label"], "本次 0 项  +0  -0")

            inclusive = CodexTelemetry(
                root,
                git_cache_seconds=0,
                git_exclude_patterns=(".DS_Store",),
                include_mode_only=True,
            )
            inclusive_task = inclusive.task_for(root / "rollout-019ffd18-a03f-7cd2-a003-9521a17e3090.jsonl")
            inclusive_task.session_id = "019ffd18-a03f-7cd2-a003-9521a17e3090"
            inclusive_task.cwd = str(root)
            inclusive_task.git_sha = baseline
            inclusive_task.status = "running"
            inclusive_task.updated_at = 1786669201
            self.assertEqual(inclusive.snapshot()["git_change_label"], "本次 1 项  +0  -0")

    def test_turn_scope_uses_turn_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            source = root / "app.py"
            source.write_text("one\n", encoding="utf-8")
            subprocess.run(["git", "add", "app.py"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "task baseline"], cwd=root, check=True)
            task_baseline = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
            source.write_text("one\ntwo\n", encoding="utf-8")
            subprocess.run(["git", "commit", "-qam", "turn baseline"], cwd=root, check=True)
            turn_baseline = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
            source.write_text("one\ntwo\nthree\n", encoding="utf-8")

            tracker = CodexTelemetry(root, git_cache_seconds=0, task_stats_scope="turn")
            task = tracker.task_for(root / "rollout-019ffd23-fd68-7952-afc5-78495e834d2e.jsonl")
            task.session_id = "019ffd23-fd68-7952-afc5-78495e834d2e"
            task.cwd = str(root)
            task.git_sha = task_baseline
            task.turn_git_sha = turn_baseline
            task.status = "running"
            task.updated_at = 1786669201
            self.assertEqual(tracker.snapshot()["git_change_label"], "本次 1 项  +1  -0")

    def test_service_scope_uses_first_observed_head(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            source = root / "app.py"
            source.write_text("one\n", encoding="utf-8")
            subprocess.run(["git", "add", "app.py"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "baseline"], cwd=root, check=True)

            tracker = CodexTelemetry(root, git_cache_seconds=0, task_stats_scope="service")
            task = tracker.task_for(root / "rollout-019ffd23-fd68-7952-afc5-78495e834d2e.jsonl")
            task.session_id = "019ffd23-fd68-7952-afc5-78495e834d2e"
            task.cwd = str(root)
            task.status = "running"
            task.updated_at = 1786669201
            self.assertEqual(tracker.snapshot()["git_change_label"], "本次 0 项  +0  -0")

            source.write_text("one\ntwo\n", encoding="utf-8")
            self.assertEqual(tracker.snapshot()["git_change_label"], "本次 1 项  +1  -0")


if __name__ == "__main__":
    unittest.main()
