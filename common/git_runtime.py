from __future__ import annotations

import os


def git_environment(*, network: bool = False) -> dict[str, str]:
    """Return a predictable Git environment suitable for a hidden service."""

    environment = {**os.environ, "LC_ALL": "C"}
    if network:
        environment.update(
            {
                "GIT_TERMINAL_PROMPT": "0",
                "GCM_INTERACTIVE": "Never",
            }
        )
    return environment


def classify_git_error(message: str) -> str:
    value = message.lower()
    if any(marker in value for marker in ("authentication failed", "could not read username", "permission denied")):
        return "凭据失败"
    if any(marker in value for marker in ("cannot lock ref", "index.lock", "fetch_head.lock", "another git process")):
        return "仓库锁冲突"
    if any(marker in value for marker in ("couldn't find remote ref", "remote ref does not exist")):
        return "远端分支不存在"
    if any(
        marker in value
        for marker in (
            "could not resolve",
            "could not connect",
            "failed to connect",
            "connection refused",
            "connection reset",
            "network is unreachable",
            "error sending request",
            "timed out",
            "rpc failed",
            "http/2",
            "tls",
        )
    ):
        return "网络失败"
    return "Git 刷新失败"


def git_retry_delay(failures: int) -> int:
    schedule = (15, 30, 60, 120, 300)
    return schedule[min(max(1, failures), len(schedule)) - 1]
