"""Fixed, same-origin assets for the local/mobile status dashboard."""

from __future__ import annotations

from pathlib import Path

WEB_ROOT = Path(__file__).resolve().parents[1] / "web"
ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/dashboard": ("index.html", "text/html; charset=utf-8"),
    "/dashboard/": ("index.html", "text/html; charset=utf-8"),
    "/dashboard/app.js": ("app.js", "application/javascript; charset=utf-8"),
    "/dashboard/style.css": ("style.css", "text/css; charset=utf-8"),
}


def dashboard_asset(path: str) -> tuple[bytes, str] | None:
    """Resolve an exact asset route; never interpret a caller-provided file path."""
    asset = ASSETS.get(path)
    if asset is None:
        return None
    name, content_type = asset
    try:
        return (WEB_ROOT / name).read_bytes(), content_type
    except OSError:
        return None
