"""Bounded, isolated App Server account queries; never start an inference turn."""

from __future__ import annotations

import json
import os
import queue
import re
import shlex
import subprocess
import threading
import time
from collections.abc import Callable
from datetime import datetime

from usage_data import extract_credits_label, parse_usage_window, remaining_value


def split_command(value: str, *, windows: bool = False) -> list[str]:
    value = os.path.expandvars(os.path.expanduser(value.strip()))
    if not value:
        raise ValueError("CODEX_COMMAND 不能为空")
    if windows:
        # An unquoted full executable path is a supported configuration value.
        if not value.startswith(('"', "'")):
            match = re.match(r"^(.+?\.exe)(?:\s+(.*))?$", value, flags=re.IGNORECASE)
            if match:
                executable, arguments = match.groups()
                return [executable] + [part.strip('"') for part in shlex.split(arguments or "", posix=False)]
        return [
            part[1:-1] if len(part) > 1 and part[0] == part[-1] and part[0] in "\"'" else part
            for part in shlex.split(value, posix=False)
        ]
    return shlex.split(value)


def query_account_usage(
    command: list[str],
    timeout: float,
    *,
    defaults: dict[str, object],
    version: str,
    log: Callable[[str], None] | None = None,
) -> dict[str, object]:
    process = subprocess.Popen(
        command + ["app-server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        bufsize=1,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
    )
    messages: queue.Queue[dict[str, object]] = queue.Queue(maxsize=128)
    stopped = threading.Event()

    def reader() -> None:
        assert process.stdout is not None
        try:
            for line in process.stdout:
                if len(line) > 2 * 1024 * 1024:
                    continue
                try:
                    item = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if not isinstance(item, dict) or "id" not in item:
                    continue
                try:
                    messages.put(item, timeout=0.25)
                except queue.Full:
                    continue
        except (OSError, ValueError):
            pass
        finally:
            stopped.set()

    thread = threading.Thread(target=reader, name="codex-account-reader", daemon=True)
    thread.start()
    deadline = time.monotonic() + timeout

    def send(message: dict[str, object]) -> None:
        assert process.stdin is not None
        process.stdin.write(json.dumps(message) + "\n")
        process.stdin.flush()

    def request(
        identifier: int, method: str, *, request_deadline: float | None = None, params: object = None
    ) -> dict[str, object]:
        send({"id": identifier, "method": method, "params": params})
        end = min(deadline, request_deadline or deadline)
        while time.monotonic() < end:
            try:
                item = messages.get(timeout=min(0.1, max(0.001, end - time.monotonic())))
            except queue.Empty:
                if stopped.is_set():
                    raise RuntimeError("Codex App Server 已退出")
                continue
            if item.get("id") == identifier:
                result = item.get("result")
                if isinstance(result, dict):
                    return result
                raise RuntimeError("Codex 账户查询未返回有效数据")
        raise TimeoutError("Codex 账户查询超时")

    account: dict[str, object] = {}
    try:
        request(
            1,
            "initialize",
            params={
                "clientInfo": {
                    "name": "Codex-TrafficLight",
                    "title": "Codex 状态看板",
                    "version": version,
                }
            },
        )
        send({"method": "initialized", "params": {}})
        limits = request(2, "account/rateLimits/read")
        try:
            account = request(3, "account/usage/read", request_deadline=time.monotonic() + 3)
        except (RuntimeError, TimeoutError, OSError):
            if log:
                log("Codex 可选账户活动查询不可用；保留已获取额度")
    finally:
        if process.stdin:
            try:
                process.stdin.close()
            except OSError:
                pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        thread.join(timeout=1)
        if process.stdout:
            process.stdout.close()

    buckets = limits.get("rateLimitsByLimitId")
    snapshot = buckets.get("codex") if isinstance(buckets, dict) else None
    if not isinstance(snapshot, dict):
        snapshot = limits.get("rateLimits")
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("primary"), dict):
        raise RuntimeError("Codex 未返回主额度窗口")
    primary = snapshot["primary"]
    if remaining_value(primary.get("usedPercent")) is None:
        raise RuntimeError("Codex 返回的主额度数值无效")
    credits = snapshot.get("credits")
    # Prefer explicitly scoped credits, never infer token counters as a balance.
    credit_label = extract_credits_label({"credits": credits}) if isinstance(credits, dict) else ""
    credit_label = credit_label or extract_credits_label(account)
    return {
        **defaults,
        **parse_usage_window(primary, "primary"),
        **parse_usage_window(snapshot.get("secondary"), "secondary"),
        "available": True,
        "plan_type": str(snapshot.get("planType") or ""),
        "credits_available": bool(credit_label),
        "credits_label": credit_label,
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": "app_server",
    }
