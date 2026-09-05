from __future__ import annotations

import re
import unittest
from pathlib import Path

from codex_status_server import DEFAULT_STATUS_PORT, build_rainmeter_payload, build_tasks_payload

ROOT = Path(__file__).resolve().parents[1]
MAIN_SKIN = ROOT / "rainmeter" / "CodexTrafficLight" / "CodexTrafficLight.ini"
SETTINGS_SKIN = ROOT / "rainmeter" / "CodexTrafficLight" / "Settings" / "Settings.ini"
VARIABLES = ROOT / "rainmeter" / "CodexTrafficLight" / "@Resources" / "variables.inc"
HELP_SCRIPT = ROOT / "rainmeter" / "CodexTrafficLight" / "@Resources" / "show-help.ps1"
TASKS_SKIN = ROOT / "rainmeter" / "CodexTrafficLight" / "Tasks" / "Tasks.ini"


class RainmeterContractTests(unittest.TestCase):
    def test_chinese_configs_keep_utf16le_bom(self) -> None:
        for path in (MAIN_SKIN, SETTINGS_SKIN, VARIABLES, TASKS_SKIN):
            with self.subTest(path=path.name):
                raw = path.read_bytes()
                self.assertTrue(raw.startswith(b"\xff\xfe"))
                self.assertNotEqual(raw[2:4], b"\xff\xfe")
                path.read_text(encoding="utf-16")

    def test_rainmeter_protocol_has_28_fields(self) -> None:
        text = MAIN_SKIN.read_text(encoding="utf-16")
        expression = next(line[7:] for line in text.splitlines() if line.startswith("RegExp="))
        compiled = re.compile(expression)
        sample = "|".join(["1"] + [f"field-{index}" for index in range(2, 29)])
        match = compiled.fullmatch(sample)
        self.assertIsNotNone(match)
        self.assertEqual(compiled.groups, 28)
        self.assertEqual(match.group(28), "field-28")

    def test_server_payload_matches_skin_protocol(self) -> None:
        status = {
            "status": "running",
            "message": "working",
            "updated_at": "now",
            "task_usage_primary_label": "-1%",
            "task_usage_secondary_label": "-2%",
        }
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
            "other_active_projects": ["another-project", "third-project"],
            "git_branch": "main",
            "git_change_label": "本次 2 项 +10 -2",
            "git_state_label": "dirty",
            "git_cumulative_label": "待推送 1 项 +4 -0",
            "token_label": "10K tokens",
            "context_label": "context 50%",
            "health_label": "healthy",
            "model": "model",
            "reasoning_effort": "high",
        }
        payload = build_rainmeter_payload(status, usage, task)
        fields = payload.split("|")
        self.assertEqual(len(fields), 28)
        self.assertIn("project|task|并行 another-project · third-project|main", payload)
        self.assertEqual(fields[17], "本次 2 项 +10 -2")
        self.assertEqual(fields[25], "待推送 1 项 +4 -0")
        self.assertEqual(fields[11:13], ["-1%", "-2%"])

    def test_help_uses_single_chinese_launcher_per_platform(self) -> None:
        text = HELP_SCRIPT.read_text(encoding="utf-8-sig")
        self.assertIn("本机 Windows 使用", text)
        self.assertIn("win\\codex_status_server\\启动状态服务.cmd", text)
        self.assertIn("win\\codex_status_server\\启动状态服务.cmd lan", text)
        self.assertIn("./启动状态服务.command", text)

    def test_windows_exposes_one_launcher_and_keeps_maintenance_internal(self) -> None:
        service_dir = ROOT / "win" / "codex_status_server"
        internal = service_dir / ".internal"
        launcher = (service_dir / "启动状态服务.cmd").read_text(encoding="utf-8")
        self.assertIn("-WindowStyle Hidden", launcher)
        self.assertIn("attrib +h", launcher)
        self.assertNotIn("pause", launcher.lower())
        self.assertEqual([path.name for path in service_dir.glob("*.cmd")], ["启动状态服务.cmd"])
        self.assertEqual(
            sorted(
                path.name
                for path in service_dir.iterdir()
                if path.is_file()
                and not path.name.startswith(".")
                and not re.match(r"^(?:status|usage-cache|status-server).*", path.name)
            ),
            ["README.md", "启动状态服务.cmd"],
        )
        for name in (
            "start-server-background.ps1",
            "check-server-health.ps1",
            "install-login-autostart.ps1",
            "uninstall-login-autostart.ps1",
            "stop-server.ps1",
            "set-status.ps1",
            "server.py",
            "service-doctor.ps1",
        ):
            self.assertTrue((internal / name).is_file(), name)

    def test_upgrade_and_doctor_scripts_cover_legacy_runtime(self) -> None:
        installer = (ROOT / "install-rainmeter-skin.cmd").read_text(encoding="utf-8")
        migration = (
            ROOT / "rainmeter" / "CodexTrafficLight" / "@Resources" / "migrate-installed-variables.ps1"
        ).read_text(encoding="utf-8-sig")
        start = (ROOT / "win" / "codex_status_server" / ".internal" / "start-server-background.ps1").read_text(
            encoding="utf-8-sig"
        )
        doctor = (ROOT / "win" / "codex_status_server" / ".internal" / "service-doctor.ps1").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn("migrate-installed-variables.ps1", installer)
        self.assertIn('-ServiceRoot "%~dp0."', installer)
        self.assertIn('copy /Y "%USER_VARIABLES%" "%DST%\\@Resources\\variables.inc.backup-%STAMP%"', installer)
        self.assertIn("127.0.0.1:8765/rainmeter", migration)
        self.assertIn("status-server\\.log\\.\\d+", start)
        self.assertIn("status-server-(?:output|error)\\.log", start)
        self.assertIn("Get-Item -LiteralPath $RuntimeDir -Force", start)
        self.assertIn("Test-ProjectStatusProcess", doctor)
        self.assertIn("service_version", doctor)
        self.assertIn("protocol_version", doctor)
        self.assertIn('& $StartScript -HostName "127.0.0.1" -Port $ExpectedPort', doctor)
        self.assertNotIn("if (-not $expectedHealth) {", doctor)

    def test_new_chinese_powershell_scripts_keep_utf8_bom(self) -> None:
        paths = (
            ROOT / "win" / "codex_status_server" / ".internal" / "service-doctor.ps1",
            ROOT / "rainmeter" / "CodexTrafficLight" / "@Resources" / "migrate-installed-variables.ps1",
            ROOT / "rainmeter" / "CodexTrafficLight" / "@Resources" / "toggle-notifications.ps1",
            ROOT / "rainmeter" / "CodexTrafficLight" / "@Resources" / "run-service-doctor.ps1",
        )
        for path in paths:
            with self.subTest(path=path.name):
                self.assertTrue(path.read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_macos_exposes_one_launcher_and_keeps_maintenance_internal(self) -> None:
        service_dir = ROOT / "mac" / "codex_status_server"
        internal = service_dir / ".internal"
        launcher = (service_dir / "启动状态服务.command").read_text(encoding="utf-8")
        background = (internal / "start-background.command").read_text(encoding="utf-8")
        stop = (internal / "stop.command").read_text(encoding="utf-8")
        self.assertIn("0.0.0.0", launcher)
        self.assertIn("/health", background)
        self.assertIn("codex-traffic-light-status", background)
        self.assertIn("status-server.pid", stop)
        self.assertEqual([path.name for path in service_dir.glob("*.command")], ["启动状态服务.command"])
        self.assertEqual(
            sorted(
                path.name
                for path in service_dir.iterdir()
                if path.is_file()
                and not path.name.startswith(".")
                and not re.match(r"^(?:status|usage-cache|status-server).*", path.name)
            ),
            ["README.md", "启动状态服务.command"],
        )
        for name in (
            "health-check.command",
            "install-login-autostart.command",
            "uninstall-login-autostart.command",
            "set-status.sh",
            "server.py",
        ):
            self.assertTrue((internal / name).is_file(), name)

    def test_expandable_task_skin_and_doctor_are_wired(self) -> None:
        main = MAIN_SKIN.read_text(encoding="utf-16")
        tasks = TASKS_SKIN.read_text(encoding="utf-16")
        variables = VARIABLES.read_text(encoding="utf-16")
        settings = SETTINGS_SKIN.read_text(encoding="utf-16")
        self.assertIn('LeftMouseUpAction=[!ToggleConfig "#ROOTCONFIG#\\Tasks" "Tasks.ini"]', main)
        self.assertIn("TasksUrl=http://127.0.0.1:8767/tasks", variables)
        self.assertIn("URL=#TasksUrl#", tasks)
        self.assertIn("StringIndex=21", tasks)
        expression = next(line[7:] for line in tasks.splitlines() if line.startswith("RegExp="))
        self.assertIsNotNone(re.compile(expression).fullmatch(build_tasks_payload({"active_tasks": []})))
        self.assertIn("体检并修复服务", settings)
        self.assertIn("任务通知设置", settings)
        self.assertIn("[MeasureServiceVersionParent]", main)
        self.assertIn("IfMatch=^0\\.4\\.0$", main)
        self.assertIn("[MeterVersionWarning]", main)
        self.assertIn("[MeterTaskClickOverlay]", main)

    def test_default_status_port_is_8767_across_service_and_skin(self) -> None:
        self.assertEqual(DEFAULT_STATUS_PORT, 8767)
        variables = VARIABLES.read_text(encoding="utf-16")
        self.assertIn("StatusUrl=http://127.0.0.1:8767/rainmeter", variables)
        self.assertIn("JsonStatusUrl=http://127.0.0.1:8767/status", variables)
        self.assertIn("TasksUrl=http://127.0.0.1:8767/tasks", variables)

        mac_background = (ROOT / "mac" / "codex_status_server" / ".internal" / "start-background.command").read_text(
            encoding="utf-8"
        )
        win_background = (ROOT / "win" / "codex_status_server" / ".internal" / "start-server-background.ps1").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn('PORT="${PORT:-8767}"', mac_background)
        self.assertIn("[int]$Port = 8767", win_background)

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

    def test_task_card_has_compact_five_row_layout(self) -> None:
        text = MAIN_SKIN.read_text(encoding="utf-16")
        sections = {name: body for name, body in re.findall(r"(?ms)^\[([^]]+)\]\r?\n(.*?)(?=^\[|\Z)", text)}

        panel = sections["MeterTaskPanel"]
        icons = sections["MeterTaskCardIcons"]
        self.assertIn("Shape2=Line 12,41,176,41", panel)
        self.assertIn("Shape7=Line 12,72,176,72", panel)
        self.assertIn("Shape8=Line 12,103,176,103", panel)
        self.assertIn("Shape9=Line 12,134,176,134", panel)
        self.assertIn("Shape=Rectangle 2,2,20,20,5", icons)
        self.assertIn("Shape11=Line 8,42,8,55", icons)
        self.assertIn("Shape17=Ellipse 8,75,5", icons)
        self.assertIn("Shape21=Rectangle 4,108,3,8,1", icons)
        self.assertIn("Shape24=Ellipse 12,140,8", icons)

        for name in ("MeterProject", "MeterGitBranch", "MeterGitState", "MeterTaskTokens", "MeterContext"):
            with self.subTest(section=name):
                self.assertRegex(sections[name], r"(?m)^X=(?:46|48)$")
                self.assertNotIn("Hidden=1", sections[name])

        for name in (
            "MeterActiveTasks",
            "MeterTaskTitle",
            "MeterGitChange",
            "MeterGitCumulative",
            "MeterModel",
            "MeterHealth",
        ):
            with self.subTest(section=name):
                self.assertIn("Hidden=1", sections[name])

        self.assertIn("Text=[MeasureGitStateCompact]", sections["MeterGitState"])
        self.assertIn('Substitute="云端 ":"云端","跟踪 ":"云端","":"云端--"', sections["MeasureGitStateCompact"])

    def test_update_interval_has_one_configuration_source(self) -> None:
        self.assertNotIn("UpdateInterval=", MAIN_SKIN.read_text(encoding="utf-16"))
        self.assertNotIn("UpdateInterval=", SETTINGS_SKIN.read_text(encoding="utf-16"))
        variable_lines = VARIABLES.read_text(encoding="utf-16").splitlines()
        self.assertEqual([line for line in variable_lines if line.startswith("UpdateInterval=")], ["UpdateInterval=1"])

    def test_parallel_project_row_is_hidden_in_compact_card(self) -> None:
        text = MAIN_SKIN.read_text(encoding="utf-16")
        sections = {name: body for name, body in re.findall(r"(?ms)^\[([^]]+)\]\r?\n(.*?)(?=^\[|\Z)", text)}
        parallel = sections["MeterActiveTasks"]
        self.assertIn("Hidden=1", parallel)

    def test_compact_context_is_left_aligned_with_other_rows(self) -> None:
        text = MAIN_SKIN.read_text(encoding="utf-16")
        sections = {name: body for name, body in re.findall(r"(?ms)^\[([^]]+)\]\r?\n(.*?)(?=^\[|\Z)", text)}
        context = sections["MeterContext"]
        self.assertIn("X=46", context)
        self.assertIn("W=140", context)
        self.assertNotIn("StringAlign=Right", context)

    def test_git_labels_distinguish_task_and_cloud_colors(self) -> None:
        text = MAIN_SKIN.read_text(encoding="utf-16")
        sections = {name: body for name, body in re.findall(r"(?ms)^\[([^]]+)\]\r?\n(.*?)(?=^\[|\Z)", text)}
        for name in ("MeterGitBranch", "MeterGitChange"):
            with self.subTest(section=name):
                self.assertIn("FontColor=#TextColor#", sections[name])
        for name in ("MeterGitState", "MeterGitCumulative"):
            with self.subTest(section=name):
                self.assertIn("FontColor=#AccentTextColor#", sections[name])
        self.assertIn("InlineSetting=Color | #LowQuotaTextColor#", sections["MeterGitState"])
        self.assertIn(r"InlinePattern=^云端(?:落后|有更新).*$", sections["MeterGitState"])

    def test_primary_usage_delta_does_not_overlap_main_value(self) -> None:
        text = MAIN_SKIN.read_text(encoding="utf-16")
        sections = {name: body for name, body in re.findall(r"(?ms)^\[([^]]+)\]\r?\n(.*?)(?=^\[|\Z)", text)}
        value = sections["MeterUsagePrimaryValue"]
        pill = sections["MeterUsagePrimaryDeltaPill"]

        value_center_y = int(re.search(r"(?m)^Y=(\d+)$", value).group(1))
        value_height = int(re.search(r"(?m)^H=(\d+)$", value).group(1))
        pill_y = int(re.search(r"(?m)^Y=(\d+)$", pill).group(1))
        pill_height = int(re.search(r"Shape=Rectangle 0,0,\d+,(\d+),", pill).group(1))

        self.assertLessEqual(pill_y + pill_height, value_center_y - value_height // 2)


if __name__ == "__main__":
    unittest.main()
