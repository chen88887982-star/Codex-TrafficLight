from __future__ import annotations

import re
import unittest
from pathlib import Path

from codex_status_server import build_rainmeter_payload

ROOT = Path(__file__).resolve().parents[1]
MAIN_SKIN = ROOT / "rainmeter" / "CodexTrafficLight" / "CodexTrafficLight.ini"
SETTINGS_SKIN = ROOT / "rainmeter" / "CodexTrafficLight" / "Settings" / "Settings.ini"
VARIABLES = ROOT / "rainmeter" / "CodexTrafficLight" / "@Resources" / "variables.inc"


class RainmeterContractTests(unittest.TestCase):
    def test_chinese_configs_keep_utf16le_bom(self) -> None:
        for path in (MAIN_SKIN, SETTINGS_SKIN, VARIABLES):
            with self.subTest(path=path.name):
                raw = path.read_bytes()
                self.assertTrue(raw.startswith(b"\xff\xfe"))
                self.assertNotEqual(raw[2:4], b"\xff\xfe")
                path.read_text(encoding="utf-16")

    def test_rainmeter_protocol_has_26_fields(self) -> None:
        text = MAIN_SKIN.read_text(encoding="utf-16")
        expression = next(line[7:] for line in text.splitlines() if line.startswith("RegExp="))
        compiled = re.compile(expression)
        sample = "|".join(["1"] + [f"field-{index}" for index in range(2, 27)])
        match = compiled.fullmatch(sample)
        self.assertIsNotNone(match)
        self.assertEqual(compiled.groups, 26)
        self.assertEqual(match.group(26), "field-26")

    def test_server_payload_matches_skin_protocol(self) -> None:
        status = {"status": "running", "message": "working", "updated_at": "now"}
        usage = {
            "primary_remaining_percent": "70%",
            "primary_resets_at": "tomorrow",
            "primary_remaining_value": 70,
            "sync_label": "fresh",
        }
        task = {
            "stage": "coding",
            "elapsed_seconds": 90,
            "project": "project",
            "task_title": "task",
            "other_active_count": 2,
            "other_active_project": "another-project",
            "git_branch": "main",
            "git_change_label": "本次 2 项 +10 -2",
            "git_state_label": "dirty",
            "git_cumulative_label": "待同步 1 项 +4 -0",
            "token_label": "10K tokens",
            "context_label": "context 50%",
            "health_label": "healthy",
            "model": "model",
            "reasoning_effort": "high",
        }
        payload = build_rainmeter_payload(status, usage, task)
        fields = payload.split("|")
        self.assertEqual(len(fields), 26)
        self.assertIn("project|task|another-project|main", payload)
        self.assertEqual(fields[17], "本次 2 项 +10 -2")
        self.assertEqual(fields[25], "待同步 1 项 +4 -0")

    def test_task_card_and_dynamic_credits_are_present(self) -> None:
        text = MAIN_SKIN.read_text(encoding="utf-16")
        for section in (
            "[MeterTaskPanel]",
            "[MeterProject]",
            "[MeterTaskTitle]",
            "[MeterGitChange]",
            "[MeterTaskTokens]",
            "[MeterHealth]",
            "[MeasureCreditsAvailable]",
        ):
            self.assertIn(section, text)
        self.assertIn("[MeterGitCumulative]", text)
        self.assertIn("SkinHeight=736", VARIABLES.read_text(encoding="utf-16"))

    def test_update_interval_has_one_configuration_source(self) -> None:
        self.assertNotIn("UpdateInterval=", MAIN_SKIN.read_text(encoding="utf-16"))
        self.assertNotIn("UpdateInterval=", SETTINGS_SKIN.read_text(encoding="utf-16"))
        variable_lines = VARIABLES.read_text(encoding="utf-16").splitlines()
        self.assertEqual([line for line in variable_lines if line.startswith("UpdateInterval=")], ["UpdateInterval=1"])

    def test_parallel_project_has_its_own_full_width_row(self) -> None:
        text = MAIN_SKIN.read_text(encoding="utf-16")
        sections = {name: body for name, body in re.findall(r"(?ms)^\[([^]]+)\]\r?\n(.*?)(?=^\[|\Z)", text)}
        parallel = sections["MeterActiveTasks"]
        self.assertIn("X=22", parallel)
        self.assertIn("W=164", parallel)
        self.assertNotIn("StringAlign=Right", parallel)

    def test_right_aligned_task_fields_stay_inside_card(self) -> None:
        text = MAIN_SKIN.read_text(encoding="utf-16")
        sections = {name: body for name, body in re.findall(r"(?ms)^\[([^]]+)\]\r?\n(.*?)(?=^\[|\Z)", text)}
        for name in ("MeterGitChange", "MeterContext", "MeterHealth"):
            with self.subTest(section=name):
                self.assertIn("X=186", sections[name])
                self.assertIn("StringAlign=Right", sections[name])

    def test_git_labels_distinguish_task_and_cloud_colors(self) -> None:
        text = MAIN_SKIN.read_text(encoding="utf-16")
        sections = {name: body for name, body in re.findall(r"(?ms)^\[([^]]+)\]\r?\n(.*?)(?=^\[|\Z)", text)}
        for name in ("MeterGitBranch", "MeterGitChange"):
            with self.subTest(section=name):
                self.assertIn("FontColor=#TextColor#", sections[name])
        for name in ("MeterGitState", "MeterGitCumulative"):
            with self.subTest(section=name):
                self.assertIn("FontColor=#AccentTextColor#", sections[name])


if __name__ == "__main__":
    unittest.main()
