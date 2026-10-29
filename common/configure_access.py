"""Prepare a private LAN access token without replacing existing user settings."""

from __future__ import annotations

import json
import secrets
import sys
from pathlib import Path

from service_runtime import atomic_write_json

CONFIG_PATH = Path(__file__).resolve().parents[1] / "status-auth.json"
EXAMPLE_TOKEN = "请替换为只在你设备间使用的长随机字符串"


def configure_access(path: Path) -> str:
    try:
        settings = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        settings = {}
    if not isinstance(settings, dict):
        raise ValueError("私有配置必须是 JSON 对象，请先检查原文件")
    token = settings.get("access_token")
    if token is not None and not isinstance(token, str):
        raise ValueError("access_token 必须是字符串，请先检查原文件")
    if token and token.strip() and token != EXAMPLE_TOKEN:
        return token
    token = secrets.token_urlsafe(32)
    atomic_write_json(path, {**settings, "access_token": token})
    return token


def main(path: Path | None = None) -> int:
    try:
        token = configure_access(path or CONFIG_PATH)
    except (OSError, ValueError) as exc:
        print(f"配置未完成：{exc}", file=sys.stderr)
        return 1
    print("跨电脑访问令牌已准备好，已有设置与有效令牌会保留。")
    print("仅粘贴到自己的 Rainmeter 地址和浏览器看板，请勿分享此令牌：")
    print(token)
    print("重启状态服务后生效；同机 127.0.0.1 访问仍不需要令牌。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
