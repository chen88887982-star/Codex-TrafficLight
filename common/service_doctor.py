"""Read-only local service diagnosis; never stop or replace a listener."""

from __future__ import annotations

import json
import os
import shlex
import socket
import subprocess
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

from service_metadata import RAINMETER_PROTOCOL_VERSION, SERVICE_NAME, SERVICE_VERSION


def validate_health(payload: object) -> list[str]:
    if not isinstance(payload, dict):
        return ["健康接口没有返回 JSON 对象"]
    issues = []
    for key, expected in (
        ("service", SERVICE_NAME),
        ("service_version", SERVICE_VERSION),
        ("protocol_version", RAINMETER_PROTOCOL_VERSION),
    ):
        if payload.get(key) != expected:
            issues.append(f"{key} 不匹配：期望 {expected}，实际 {payload.get(key)}")
    if payload.get("status") not in {"ok", "degraded"}:
        issues.append(f"服务健康异常：{payload.get('status')}")
    return issues


def diagnose(service_dir: Path, port: int) -> dict[str, object]:
    issues: list[str] = []
    warnings: list[str] = []
    health: object = None
    try:
        with build_opener(ProxyHandler({})).open(f"http://127.0.0.1:{port}/health", timeout=3) as response:
            health = json.load(response)
        issues.extend(validate_health(health))
        if isinstance(health, dict) and health.get("status") == "degraded":
            warnings.extend(str(item) for item in health.get("reasons", []) if isinstance(item, str))
    except (OSError, URLError, ValueError) as exc:
        issues.append(f"健康接口不可用：{type(exc).__name__}")
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            listening = True
    except OSError:
        listening = False
    pid_path = service_dir / ".runtime" / "status-server.pid"
    process_state = "未记录"
    try:
        pid = int(json.loads(pid_path.read_text())["pid"])
        if pid <= 0:
            raise ValueError("invalid PID")
        command = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, timeout=3)
        expected = (service_dir / ".internal" / "server.py").resolve()
        arguments = shlex.split(command.stdout)
        matches = any(Path(arg).is_absolute() and Path(arg).resolve() == expected for arg in arguments)
        process_state = "本项目服务正在运行" if command.returncode == 0 and matches else "PID 已失效或属于其他进程"
        if process_state != "本项目服务正在运行":
            issues.append(process_state)
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
        issues.append("PID 文件缺失、无效或进程无法核验")
    launch_agents = Path.home() / "Library" / "LaunchAgents"
    autostart = []
    for path in launch_agents.glob("*codex*.plist"):
        try:
            if str(service_dir) in path.read_text():
                autostart.append(path.name)
        except OSError:
            continue
    components = health.get("components", {}) if isinstance(health, dict) else {}
    checks = {
        "listener": {"status": "ok" if listening else "error", "label": "端口正在监听" if listening else "端口未监听"},
        "process": {"status": "ok" if process_state == "本项目服务正在运行" else "error", "label": process_state},
        "version": {
            "status": "ok" if isinstance(health, dict) and not validate_health(health) else "error",
            "label": f"服务 {SERVICE_VERSION} / 协议 {RAINMETER_PROTOCOL_VERSION}",
        },
        "monitor": components.get("monitor", {"status": "unknown", "label": "未返回监控详情"}),
        "usage": components.get("usage", {"status": "unknown", "label": "未返回额度详情"}),
        "git": components.get("git", {"status": "unknown", "label": "未返回 Git 详情"}),
    }
    return {
        "ok": not issues,
        "port": port,
        "listening": listening,
        "process": process_state,
        "health": health,
        "issues": issues,
        "warnings": warnings,
        "checks": checks,
        "mode": "check",
        "login_autostart_files": autostart,
        "log_directory": str(service_dir / ".runtime"),
        "next_step": "基础运行检查通过；存在降级项，请查看 warnings 与分项检查"
        if not issues and warnings
        else "检查通过"
        if not issues
        else "查看运行日志；通过本项目停止入口核验旧进程，再使用启动入口重启。不会自动结束占用端口的进程。",
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Codex 状态服务只读体检")
    parser.add_argument("--service-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        port = int(os.environ.get("PORT", "8767"))
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        parser.error("PORT 必须为 1..65535")
    report = diagnose(args.service_dir.resolve(), port)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
