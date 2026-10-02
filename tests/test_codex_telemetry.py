from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_status_server import (
    extract_credits_label,
    read_env_bool,
    read_env_choice,
    read_env_float,
    read_env_int,
    read_env_interval,
    resolve_codex_command,
    resolve_expose_task_details,
)
from codex_telemetry import (
    CodexTelemetry,
    compact_number,
    compact_task_title,
    count_unified_diff,
    friendly_tool_stage,
    parse_timestamp,
)
from service_runtime import JsonlFollower


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
            {
                "TEST_INT": "0",
                "TEST_FLOAT": "nan",
                "TEST_BOOL": "maybe",
                "TEST_CHOICE": "unknown",
                "TEST_INTERVAL": "5",
            },
            clear=False,
        ):
            self.assertEqual(read_env_int("TEST_INT", 10, 1, 20), 10)
            self.assertEqual(read_env_interval("TEST_INTERVAL", 900, 60, 86400), 900)
            self.assertEqual(read_env_float("TEST_FLOAT", 2.5, 0.1, 10), 2.5)
            self.assertTrue(read_env_bool("TEST_BOOL", True))
            self.assertEqual(read_env_choice("TEST_CHOICE", "task", {"task", "turn"}), "task")

    def test_codex_command_uses_path_when_no_override_is_set(self) -> None:
        with (
            patch("codex_status_server.CODEX_COMMAND", ""),
            patch.dict("codex_status_server.os.environ", {"LOCALAPPDATA": ""}, clear=False),
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
        self.assertEqual(compact_task_title("  第一行\n 第二行  "), "第一行 第二行")

    def test_current_custom_tool_events_and_turn_title_are_tracked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tracker = CodexTelemetry(root)
            path = root / "rollout-019ffd23-fd68-7952-afc5-78495e834d2e.jsonl"
            tracker.ingest(
                {
                    "timestamp": "2026-08-14T01:00:00Z",
                    "type": "session_meta",
                    "payload": {"id": "019ffd23-fd68-7952-afc5-78495e834d2e", "cwd": str(root / "project")},
                },
                path,
            )
            tracker.ingest(event("2026-08-14T01:00:01Z", "user_message", message="优化当前轮任务标题"), path)
            tracker.ingest(event("2026-08-14T01:00:02Z", "task_started", turn_id="turn"), path)
            result = tracker.ingest(
                {
                    "timestamp": "2026-08-14T01:00:03Z",
                    "type": "response_item",
                    "payload": {"type": "custom_tool_call", "name": "exec", "input": "git status"},
                },
                path,
            )
            self.assertEqual(result, "running")
            self.assertEqual(tracker.snapshot()["stage"], "正在运行命令")
            self.assertEqual(tracker.snapshot()["task_title"], "优化当前轮任务标题")

            result = tracker.ingest(
                {
                    "timestamp": "2026-08-14T01:00:04Z",
                    "type": "response_item",
                    "payload": {
                        "type": "custom_tool_call",
                        "name": "exec",
                        "input": '{"sandbox_permissions":"require_escalated"}',
                    },
                },
                path,
            )
            self.assertEqual(result, "waiting")
            self.assertEqual(tracker.snapshot()["stage"], "等待用户确认")
            tracker.ingest(
                {
                    "timestamp": "2026-08-14T01:00:05Z",
                    "type": "response_item",
                    "payload": {"type": "custom_tool_call_output", "output": "done"},
                },
                path,
            )
            self.assertEqual(tracker.snapshot()["stage"], "正在处理工具结果")
            tracker.ingest(event("2026-08-14T01:00:06Z", "agent_reasoning", text="thinking"), path)
            self.assertEqual(tracker.snapshot()["stage"], "正在分析任务")

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
            self.assertEqual(snapshot["other_active_projects"], ["one"])
            self.assertEqual([item["project"] for item in snapshot["active_tasks"]], ["two", "one"])

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

    def test_response_user_titles_follow_started_turn_and_skip_injected_context(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tracker = CodexTelemetry(root)
            path = root / "rollout-019ffd23-fd68-7952-afc5-78495e834d2e.jsonl"
            tracker.ingest(event("2026-10-03T01:00:00Z", "task_started", turn_id="t1"), path)

            def user_message(text: str) -> dict[str, object]:
                return {
                    "timestamp": "2026-10-03T01:00:01Z",
                    "type": "response_item",
                    "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]},
                }

            tracker.ingest(user_message("全部开始优化 升级 开发\n"), path)
            self.assertEqual(tracker.snapshot()["task_title"], "全部开始优化 升级 开发")
            for context in (
                '<external_codex_apps_open_page>{"page_id":null}</external_codex_apps_open_page>',
                "<environment_context>private environment</environment_context>",
                "# AGENTS.md instructions\n<INSTRUCTIONS>do not store this</INSTRUCTIONS>",
            ):
                tracker.ingest(user_message(context), path)
                self.assertEqual(tracker.snapshot()["task_title"], "全部开始优化 升级 开发")
            self.assertEqual(tracker.task_for(path).status, "running")

    def test_rebuild_cursor_captures_startup_gap_and_partial_line(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "rollout-019ffd23-fd68-7952-afc5-78495e834d2e.jsonl"
            path.write_text(json.dumps(event("2026-10-03T01:00:00Z", "task_started", turn_id="t1")) + "\n")
            tracker = CodexTelemetry(root)
            offsets = tracker.rebuild([path])
            with path.open("a") as handle:
                handle.write(json.dumps(event("2026-10-03T01:00:01Z", "task_complete", turn_id="t1")) + "\n")
            follower = JsonlFollower()
            follower.start_at_offset(path, offsets[path.resolve()])
            for line in follower.read_lines(path):
                tracker.ingest(json.loads(line), path)
            self.assertEqual(tracker.snapshot()["status"], "success")

    def test_rebuild_large_tool_record_keeps_start_and_turn_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "rollout-019ffd23-fd68-7952-afc5-78495e834d2e.jsonl"
            records = [
                event("2026-10-03T01:00:00Z", "task_started", turn_id="long-turn"),
                {
                    "timestamp": "2026-10-03T01:00:01Z",
                    "type": "response_item",
                    "payload": {"type": "custom_tool_call_output", "output": "x" * (9 * 1024 * 1024)},
                },
            ]
            path.write_text("\n".join(json.dumps(item) for item in records) + "\n")
            tracker = CodexTelemetry(root)
            offsets = tracker.rebuild([path])
            self.assertEqual(offsets[path.resolve()], path.stat().st_size)
            self.assertEqual(tracker.snapshot()["status"], "running")
            self.assertEqual(tracker.snapshot()["turn_id"], "long-turn")

    def test_rebuild_skips_bad_records_and_nonfinite_fields_without_losing_completion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "rollout-019ffd23-fd68-7952-afc5-78495e834d2e.jsonl"
            records = [
                event("2026-10-03T01:00:00Z", "task_started", turn_id="t1"),
                [],
                None,
                event(
                    float("inf"),
                    "token_count",
                    info={"last_token_usage": {"total_tokens": float("inf")}, "model_context_window": {"bad": "type"}},
                ),
                event("2026-10-03T01:00:02Z", "task_complete", turn_id="t1", duration_ms=float("nan")),
            ]
            path.write_text("\n".join(json.dumps(item) for item in records) + "\n")
            tracker = CodexTelemetry(root)
            offsets = tracker.rebuild([path])
            self.assertEqual(offsets[path.resolve()], path.stat().st_size)
            self.assertEqual(tracker.snapshot()["status"], "success")
            self.assertEqual(tracker.task_for(path).last_tokens, 0)
            for value in (float("nan"), float("inf"), -float("inf"), 10**400):
                self.assertEqual(parse_timestamp(value), 0)
                self.assertEqual(compact_number(value), "--")

    def test_rebuild_isolates_single_record_decoder_error_and_continues_other_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = [root / f"rollout-019ffd23-fd68-7952-afc5-78495e834d2{index}.jsonl" for index in (1, 2)]
            for path in paths:
                records = [
                    event("2026-10-03T01:00:00Z", "task_started", turn_id="t1"),
                    event("2026-10-03T01:00:01Z", "bad_adapter_record"),
                    event("2026-10-03T01:00:02Z", "task_complete", turn_id="t1"),
                ]
                path.write_text("\n".join(json.dumps(item) for item in records) + "\n")
            tracker = CodexTelemetry(root)
            original = tracker.ingest

            def decode(record: dict, path: Path, **kwargs: object) -> str:
                if record["payload"]["type"] == "bad_adapter_record":
                    raise ValueError("invalid upstream field")
                return original(record, path, **kwargs)

            with patch.object(tracker, "ingest", side_effect=decode):
                offsets = tracker.rebuild(paths)
            self.assertEqual(len(offsets), 2)
            self.assertTrue(all(tracker.task_for(path).status == "success" for path in paths))

    def test_task_selection_ignore_and_recheck_only_change_monitoring(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tracker = CodexTelemetry(root)
            paths = []
            for index in (1, 2):
                path = root / f"rollout-019ffd23-fd68-7952-afc5-78495e834d2{index}.jsonl"
                paths.append(path)
                started = event(f"2026-10-03T01:00:0{index}Z", "task_started", turn_id=f"t{index}")
                path.write_text(json.dumps(started) + "\n")
                tracker.ingest(started, path)
            first = tracker.task_for(paths[0])
            second = tracker.task_for(paths[1])
            self.assertEqual(tracker.snapshot()["session_id"], second.session_id)
            self.assertTrue(tracker.control_task("pin", first.session_id)["ok"])
            self.assertEqual(tracker.snapshot()["session_id"], first.session_id)
            tracker.control_task("unpin")
            self.assertEqual(tracker.snapshot()["session_id"], second.session_id)
            tracker.control_task("ignore", second.session_id, second.turn_id)
            self.assertEqual(second.status, "running")
            self.assertNotIn(paths[1].resolve(), tracker.active_paths())
            tracker.ingest(event("2026-10-03T01:00:03Z", "task_started", turn_id="t3"), paths[1])
            self.assertIn(paths[1].resolve(), tracker.active_paths())
            with paths[0].open("a") as handle:
                handle.write(json.dumps(event("2026-10-03T01:00:04Z", "task_complete", turn_id="t1")) + "\n")
            self.assertTrue(tracker.control_task("recheck", first.session_id)["ok"])
            self.assertEqual(tracker.task_for(paths[0]).status, "success")
            self.assertFalse(tracker.control_task("ignore", second.session_id, "old-turn")["ok"])

    def test_git_pending_push_excludes_remote_only_changes_and_reads_nested_untracked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def git(*args: str) -> str:
                return subprocess.check_output(["git", *args], cwd=root, text=True).strip()

            git("init", "-q")
            git("config", "user.name", "Test")
            git("config", "user.email", "test@example.com")
            sub = root / "sub"
            sub.mkdir()
            tracked = sub / "tracked.txt"
            tracked.write_text("one\n")
            git("add", ".")
            git("commit", "-qm", "baseline")
            git("branch", "-m", "main")
            baseline = git("rev-parse", "HEAD")
            git("checkout", "-qb", "remote-work")
            tracked.write_text("one\ntwo\nthree\n")
            git("commit", "-qam", "remote-only")
            remote = git("rev-parse", "HEAD")
            git("checkout", "-q", "main")
            git("remote", "add", "origin", str(root / "unused.git"))
            git("update-ref", "refs/remotes/origin/main", remote)
            git("branch", "--set-upstream-to=origin/main")
            tracker = CodexTelemetry(root, git_cache_seconds=0)
            task = tracker.task_for(root / "session.jsonl")
            task.cwd = str(sub)
            task.git_sha = baseline
            stats = tracker._git_stats(task)
            self.assertEqual(stats["git_behind"], 1)
            self.assertEqual(stats["git_sync_files"], 0)
            self.assertEqual(stats["git_sync_deleted"], 0)
            self.assertEqual(stats["git_pull_added"], 2)
            self.assertEqual(stats["git_worktree_files"], 0)
            self.assertEqual(stats["git_worktree_label"], "工作区干净")
            (sub / "new.txt").write_text("a\nb\nc\n")
            stats = tracker._git_stats(task, use_cache=False)
            self.assertEqual(stats["git_added"], 3)
            self.assertEqual(stats["git_sync_added"], 3)
            self.assertEqual(stats["git_worktree_files"], 1)
            self.assertEqual(stats["git_worktree_added"], 3)
            self.assertEqual(stats["git_worktree_deleted"], 0)

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
            self.assertEqual(snapshot["active_tasks"], [])

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
            self.assertEqual(snapshot["git_cumulative_label"], "待推送 1 项  +1  -0")
            self.assertEqual(snapshot["git_task_label"], "本次 1 项  +1  -0")
            self.assertEqual(snapshot["git_sync_label"], "待推送 1 项  +1  -0")
            self.assertEqual(snapshot["git_sync_files"], 1)
            self.assertEqual(snapshot["git_worktree_files"], 1)
            self.assertEqual(snapshot["git_worktree_added"], 1)
            self.assertEqual(snapshot["git_worktree_label"], "未提交 1 项  +1  -0")

            subprocess.run(["git", "add", "app.py"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "task change"], cwd=root, check=True)
            snapshot = tracker.snapshot()
            self.assertEqual(snapshot["git_change_label"], "本次 1 项  +1  -0")
            self.assertEqual(snapshot["git_cumulative_label"], "待推送 1 项  +1  -0")
            self.assertEqual(snapshot["git_state_label"], "跟踪 领先 1")
            self.assertEqual(snapshot["git_worktree_files"], 0)
            self.assertEqual(snapshot["git_worktree_added"], 0)
            self.assertEqual(snapshot["git_worktree_label"], "工作区干净")

            head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
            subprocess.run(["git", "update-ref", "refs/remotes/origin/main", head], cwd=root, check=True)
            snapshot = tracker.snapshot()
            self.assertEqual(snapshot["git_change_label"], "本次 1 项  +1  -0")
            self.assertEqual(snapshot["git_cumulative_label"], "待推送 0 项  +0  -0")
            self.assertEqual(snapshot["git_state_label"], "跟踪 已同步")

    def test_git_stats_support_spaces_tabs_unicode_and_renames(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            old_path = root / "旧 文件.txt"
            unicode_path = root / "中文 文件.txt"
            old_path.write_text("old\n", encoding="utf-8")
            unicode_path.write_text("one\n", encoding="utf-8")
            subprocess.run(["git", "add", "--", old_path.name, unicode_path.name], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "baseline"], cwd=root, check=True)
            baseline = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
            subprocess.run(["git", "mv", "--", old_path.name, "新 名称.txt"], cwd=root, check=True)
            unicode_path.write_text("one\ntwo\n", encoding="utf-8")
            tabbed_name = "制表 文件.txt" if os.name == "nt" else "制表\t文件.txt"
            (root / tabbed_name).write_text("a\nb\n", encoding="utf-8")

            tracker = CodexTelemetry(root, git_cache_seconds=0)
            task = tracker.task_for(root / "rollout-019ffd23-fd68-7952-afc5-78495e834d2e.jsonl")
            task.session_id = "019ffd23-fd68-7952-afc5-78495e834d2e"
            task.cwd = str(root)
            task.git_sha = baseline
            task.status = "running"
            task.updated_at = time.time()
            snapshot = tracker.snapshot()
            self.assertTrue(snapshot["git_dirty"])
            self.assertEqual(snapshot["git_files"], 3)
            self.assertEqual(snapshot["git_added"], 3)
            self.assertEqual(snapshot["git_deleted"], 0)

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

    def test_background_git_statistics_do_not_block_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tracker = CodexTelemetry(root, background_git_statistics=True)
            path = root / "rollout-019ffd23-fd68-7952-afc5-78495e834d2e.jsonl"
            task = tracker.task_for(path)
            task.session_id = "019ffd23-fd68-7952-afc5-78495e834d2e"
            task.cwd = str(root)
            task.status = "running"
            task.updated_at = time.time()
            release = threading.Event()
            finished = threading.Event()

            def slow_git(*args: object, **kwargs: object) -> dict[str, object]:
                release.wait(timeout=2)
                finished.set()
                return {**tracker._empty_git_stats(task), "git_branch": "background"}

            with patch.object(tracker, "_git_stats", side_effect=slow_git):
                started = time.monotonic()
                snapshot = tracker.snapshot()
                elapsed = time.monotonic() - started
                self.assertLess(elapsed, 0.25)
                self.assertFalse(snapshot["git_available"])
                release.set()
                self.assertTrue(finished.wait(timeout=2))
                for _ in range(100):
                    if tracker.snapshot()["git_branch"] == "background":
                        break
                    time.sleep(0.01)
                self.assertEqual(tracker.snapshot()["git_branch"], "background")

    def test_background_fetch_detects_remote_commits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            remote = base / "remote.git"
            root = base / "work"
            publisher = base / "publisher"
            subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            source = root / "app.py"
            source.write_text("one\n", encoding="utf-8")
            subprocess.run(["git", "add", "app.py"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "baseline"], cwd=root, check=True)
            subprocess.run(["git", "branch", "-M", "main"], cwd=root, check=True)
            subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=root, check=True)
            subprocess.run(["git", "push", "-qu", "origin", "main"], cwd=root, check=True)
            subprocess.run(["git", "symbolic-ref", "HEAD", "refs/heads/main"], cwd=remote, check=True)

            subprocess.run(["git", "clone", "-q", str(remote), str(publisher)], check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=publisher, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=publisher, check=True)
            (publisher / "remote.py").write_text("remote\n", encoding="utf-8")
            subprocess.run(["git", "add", "remote.py"], cwd=publisher, check=True)
            subprocess.run(["git", "commit", "-qm", "remote change"], cwd=publisher, check=True)
            subprocess.run(["git", "push", "-q", "origin", "main"], cwd=publisher, check=True)

            tracker = CodexTelemetry(
                root,
                git_cache_seconds=60,
                git_fetch_interval_seconds=300,
                background_git_statistics=True,
            )
            task = tracker.task_for(root / "rollout-019ffd23-fd68-7952-afc5-78495e834d2e.jsonl")
            task.cwd = str(root)
            task.git_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
            task.status = "running"
            task.updated_at = time.time()

            self.assertFalse(tracker.snapshot()["git_available"])
            snapshot = {}
            for _ in range(200):
                snapshot = tracker.snapshot()
                if snapshot.get("git_behind") == 1:
                    break
                time.sleep(0.01)
            self.assertEqual(snapshot["git_behind"], 1)
            self.assertEqual(snapshot["git_state_label"], "云端 落后 1")
            self.assertEqual(snapshot["git_remote_status"], "verified")
            self.assertGreater(tracker.runtime_health()["git_fetch_last_success"], 0)
            self.assertFalse(tracker._refresh_git_tracking(str(root)))

            (publisher / "second.py").write_text("second\n", encoding="utf-8")
            subprocess.run(["git", "add", "second.py"], cwd=publisher, check=True)
            subprocess.run(["git", "commit", "-qm", "second remote change"], cwd=publisher, check=True)
            subprocess.run(["git", "push", "-q", "origin", "main"], cwd=publisher, check=True)
            tracker._git_fetch_next_attempt[str(root)] = 0
            real_run = subprocess.run

            def fail_fetch(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                if args[:2] == ["git", "fetch"]:
                    return subprocess.CompletedProcess(args, 128, "", "fatal: Failed to connect to github.com")
                return real_run(args, **kwargs)

            with patch("codex_telemetry.subprocess.run", side_effect=fail_fetch):
                self.assertFalse(tracker._refresh_git_tracking(str(root)))
            stale = tracker._git_stats(task, use_cache=False, cache_result=False)
            self.assertEqual(stale["git_state_label"], "云端 有更新")
            self.assertEqual(stale["git_remote_status"], "different")
            self.assertEqual(stale["git_remote_error_label"], "网络失败")
            self.assertEqual(stale["git_remote_retry_seconds"], 15)
            self.assertEqual(tracker.runtime_health()["git_fetch_last_error"], "网络失败")
            self.assertFalse(tracker._refresh_git_tracking(str(root)))

            tracker._git_fetch_next_attempt[str(root)] = 0
            self.assertTrue(tracker._refresh_git_tracking(str(root)))
            recovered = tracker._git_stats(task, use_cache=False, cache_result=False)
            self.assertEqual(recovered["git_state_label"], "云端 落后 2")
            self.assertEqual(recovered["git_remote_status"], "verified")
            self.assertEqual(recovered["git_remote_error_label"], "")
            self.assertEqual(tracker.runtime_health()["git_fetch_last_error"], "")

    def test_git_fetch_errors_are_safely_classified(self) -> None:
        cases = {
            "fatal: Authentication failed": "凭据失败",
            "fatal: cannot lock ref 'refs/remotes/origin/main'": "仓库锁冲突",
            "fatal: couldn't find remote ref main": "远端分支不存在",
            "fatal: unable to access URL: Failed to connect": "网络失败",
            "fatal: unexpected failure for https://secret.example": "Git 刷新失败",
        }
        for message, expected in cases.items():
            with self.subTest(message=message):
                self.assertEqual(CodexTelemetry._classify_git_error(message), expected)

    def test_prune_releases_completed_task_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tracker = CodexTelemetry(root)
            keep = root / "rollout-019ffd23-fd68-7952-afc5-78495e834d2e.jsonl"
            remove = root / "rollout-019ffd18-a03f-7cd2-a003-9521a17e3090.jsonl"
            tracker.task_for(keep).session_id = "019ffd23-fd68-7952-afc5-78495e834d2e"
            tracker.task_for(remove).session_id = "019ffd18-a03f-7cd2-a003-9521a17e3090"
            tracker.prune({keep})
            self.assertEqual(tracker.runtime_health()["tracked_tasks"], 1)

    def test_completed_task_expires_to_idle_after_hold(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tracker = CodexTelemetry(root)
            path = root / "rollout-019ffd23-fd68-7952-afc5-78495e834d2e.jsonl"
            task = tracker.task_for(path)
            task.session_id = "019ffd23-fd68-7952-afc5-78495e834d2e"
            task.status = "success"
            task.completed_at = time.time() - 60
            task.updated_at = task.completed_at
            self.assertTrue(tracker.expire_completed(45))
            self.assertEqual(tracker.snapshot()["status"], "idle")


if __name__ == "__main__":
    unittest.main()
