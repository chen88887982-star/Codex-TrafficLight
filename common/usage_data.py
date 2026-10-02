from __future__ import annotations

import math
from datetime import datetime


def format_reset_label(epoch_seconds: object, *, always_time: bool = False) -> str:
    try:
        reset_at = datetime.fromtimestamp(int(epoch_seconds)).astimezone()
    except (TypeError, ValueError, OverflowError, OSError):
        return "--"
    if always_time:
        return reset_at.strftime("%H:%M")
    now = datetime.now().astimezone()
    if reset_at.date() == now.date():
        return reset_at.strftime("%H:%M")
    return f"{reset_at.month}月{reset_at.day}日 {reset_at:%H:%M}"


def remaining_value(used_percent: object) -> int | None:
    if isinstance(used_percent, bool):
        return None
    try:
        remaining = 100 - float(used_percent)
    except (TypeError, ValueError, OverflowError):
        return None
    return max(0, min(100, math.floor(remaining))) if math.isfinite(remaining) else None


def used_percent_value(used_percent: object) -> float | None:
    if isinstance(used_percent, bool):
        return None
    try:
        used = float(used_percent)
    except (TypeError, ValueError, OverflowError):
        return None
    return max(0.0, min(100.0, used)) if math.isfinite(used) else None


def epoch_value(epoch_seconds: object) -> int | None:
    if isinstance(epoch_seconds, bool):
        return None
    try:
        return int(epoch_seconds)
    except (TypeError, ValueError, OverflowError):
        return None


def parse_timestamp(value: object) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (ValueError, OverflowError, OSError):
        return 0.0


def format_age_label(seconds: float) -> str:
    seconds = max(0.0, seconds)
    if seconds < 60:
        return "刚刚"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes} 分钟"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} 小时"
    days = hours // 24
    return f"{days} 天"


def parse_usage_window(window: object, prefix: str, *, session: bool = False) -> dict[str, object]:
    window = window if isinstance(window, dict) else {}
    used = window.get("used_percent" if session else "usedPercent")
    reset = window.get("resets_at" if session else "resetsAt")
    minutes = window.get("window_minutes" if session else "windowDurationMins")
    minutes = epoch_value(minutes)
    label = "主窗口" if prefix == "primary" else "第二窗口"
    if minutes and minutes > 0:
        if minutes % 1440 == 0:
            label = f"{minutes // 1440}天额度"
        elif minutes % 60 == 0:
            label = f"{minutes // 60}小时额度"
        else:
            label = f"{minutes}分钟额度"
    remaining = remaining_value(used)
    return {
        f"{prefix}_remaining_percent": f"{remaining}%" if remaining is not None else "",
        f"{prefix}_remaining_value": remaining,
        f"{prefix}_used_percent": used_percent_value(used),
        f"{prefix}_resets_at": format_reset_label(reset) if reset else "",
        f"{prefix}_resets_at_epoch": epoch_value(reset),
        f"{prefix}_window_minutes": minutes,
        f"{prefix}_window_label": label,
    }


def extract_credits_label(usage: dict[str, object]) -> str:
    """Read an optional credits balance without assuming a fixed experimental schema."""

    keys = ("creditsBalance", "creditBalance", "remainingCredits", "balance")
    pending: list[object] = [usage]
    while pending:
        current = pending.pop()
        if not isinstance(current, dict):
            continue
        for key in keys:
            value = current.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                try:
                    if math.isfinite(value):
                        return f"{value:g}"
                except OverflowError:
                    continue
            if isinstance(value, str) and value.strip():
                return value.strip()
        credits = current.get("credits")
        if isinstance(credits, dict):
            pending.append(credits)
        for value in current.values():
            if isinstance(value, dict) and value is not credits:
                pending.append(value)
    return ""
