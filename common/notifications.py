from __future__ import annotations

import os
import platform
import subprocess
import threading
from datetime import datetime
from datetime import time as clock_time


def _parse_clock(value: str) -> clock_time | None:
    try:
        return datetime.strptime(value.strip(), "%H:%M").time()
    except ValueError:
        return None


def in_quiet_hours(specification: str, now: datetime | None = None) -> bool:
    if not specification or "-" not in specification:
        return False
    start_text, end_text = specification.split("-", 1)
    start = _parse_clock(start_text)
    end = _parse_clock(end_text)
    if start is None or end is None or start == end:
        return False
    current = (now or datetime.now()).time()
    if start < end:
        return start <= current < end
    return current >= start or current < end


class NotificationManager:
    def __init__(
        self,
        *,
        enabled: bool = False,
        quiet_hours: str = "",
        notify_waiting: bool = True,
        notify_success: bool = True,
        notify_error: bool = True,
    ) -> None:
        self.enabled = enabled
        self.quiet_hours = quiet_hours
        self.notify_waiting = notify_waiting
        self.notify_success = notify_success
        self.notify_error = notify_error
        self._delivered: set[tuple[str, str]] = set()
        self._lock = threading.Lock()

    def notify(self, state: str, turn_id: str, project: str) -> bool:
        if not self.enabled or not turn_id or in_quiet_hours(self.quiet_hours):
            return False
        allowed = {
            "waiting": self.notify_waiting,
            "success": self.notify_success,
            "error": self.notify_error,
        }
        if not allowed.get(state, False):
            return False
        key = (turn_id, state)
        with self._lock:
            if key in self._delivered:
                return False
            self._delivered.add(key)
            if len(self._delivered) > 200:
                self._delivered = set(list(self._delivered)[-100:])
        title, message = self._message(state, project)
        threading.Thread(
            target=self._deliver,
            args=(title, message),
            name="codex-status-notification",
            daemon=True,
        ).start()
        return True

    @staticmethod
    def _message(state: str, project: str) -> tuple[str, str]:
        project = project or "Codex"
        if state == "waiting":
            return "Codex 等待确认", f"{project} 正在等待你的确认"
        if state == "success":
            return "Codex 任务完成", f"{project} 已完成"
        return "Codex 任务异常", f"{project} 已中止或发生错误"

    @staticmethod
    def _deliver(title: str, message: str) -> None:
        system = platform.system()
        try:
            if system == "Windows":
                title_literal = "'" + title.replace("'", "''") + "'"
                message_literal = "'" + message.replace("'", "''") + "'"
                script = (
                    "Add-Type -AssemblyName System.Windows.Forms;"
                    "$n=New-Object System.Windows.Forms.NotifyIcon;"
                    "$n.Icon=[System.Drawing.SystemIcons]::Information;"
                    f"$n.BalloonTipTitle={title_literal};$n.BalloonTipText={message_literal};"
                    "$n.Visible=$true;$n.ShowBalloonTip(5000);Start-Sleep -Seconds 6;$n.Dispose()"
                )
                subprocess.Popen(
                    [
                        "powershell.exe",
                        "-NoProfile",
                        "-WindowStyle",
                        "Hidden",
                        "-Command",
                        script,
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    env={**os.environ},
                )
            elif system == "Darwin":
                escaped_title = title.replace('"', '\\"')
                escaped_message = message.replace('"', '\\"')
                subprocess.Popen(
                    ["osascript", "-e", f'display notification "{escaped_message}" with title "{escaped_title}"'],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env={**os.environ},
                )
        except OSError:
            return
