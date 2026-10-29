from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from configure_access import EXAMPLE_TOKEN, configure_access, main


class AccessConfigurationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "status-auth.json"

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_generated_token_is_private_url_safe_and_stable_on_repeat(self) -> None:
        token = configure_access(self.path)
        self.assertGreaterEqual(len(token), 43)
        self.assertRegex(token, r"^[A-Za-z0-9_-]+$")
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["access_token"], token)
        previous = self.path.read_bytes()
        self.assertEqual(configure_access(self.path), token)
        self.assertEqual(self.path.read_bytes(), previous)
        if os.name != "nt":
            self.assertEqual(self.path.stat().st_mode & 0o077, 0)

    def test_adds_token_without_replacing_notification_or_custom_settings(self) -> None:
        settings = {"notifications_enabled": True, "expose_task_details": False, "custom": {"value": "保留"}}
        self.path.write_text(json.dumps(settings, ensure_ascii=False), encoding="utf-8")
        token = configure_access(self.path)
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), {**settings, "access_token": token})

    def test_existing_token_is_returned_without_rewriting_the_file(self) -> None:
        self.path.write_text('{"access_token":"existing-token", "notifications_enabled":true}', encoding="utf-8-sig")
        previous = self.path.read_bytes()
        self.assertEqual(configure_access(self.path), "existing-token")
        self.assertEqual(self.path.read_bytes(), previous)

    def test_example_placeholder_is_replaced_with_a_generated_token(self) -> None:
        self.path.write_text(json.dumps({"access_token": EXAMPLE_TOKEN}), encoding="utf-8")
        self.assertNotEqual(configure_access(self.path), EXAMPLE_TOKEN)

    def test_invalid_configuration_is_preserved(self) -> None:
        for invalid in ("{broken", "[]", '{"access_token":123}'):
            with self.subTest(invalid=invalid):
                self.path.write_text(invalid, encoding="utf-8")
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(main(self.path), 1)
                self.assertEqual(self.path.read_text(encoding="utf-8"), invalid)

    def test_failed_atomic_save_leaves_the_original_settings_intact(self) -> None:
        self.path.write_text('{"notifications_enabled":true}', encoding="utf-8")
        previous = self.path.read_bytes()
        with patch("configure_access.atomic_write_json", side_effect=OSError("disk full")):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(self.path), 1)
        self.assertEqual(self.path.read_bytes(), previous)

    def test_command_displays_the_saved_token_and_restart_instruction(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(self.path), 0)
        token = json.loads(self.path.read_text(encoding="utf-8"))["access_token"]
        self.assertIn(token, output.getvalue())
        self.assertIn("重启状态服务", output.getvalue())


if __name__ == "__main__":
    unittest.main()
