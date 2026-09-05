"""Frozen-safe filesystem roots for logs, models, and session data.

In a PyInstaller/cx_Freeze bundle, ``sys.frozen`` is set and assets live next
to the executable rather than the source tree. Callers must not write into the
install prefix; mutable data always goes under the user data directory.

Also supports PyInstaller one-file (``sys._MEIPASS``) resource resolution.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False)) or hasattr(sys, "_MEIPASS")


def install_root() -> Path:
    """Read-only install / source root (never write here in product mode)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def app_root() -> Path:
    """Directory that contains the runnable agent (or extract dir when frozen)."""
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    if is_frozen():
        return Path(sys.executable).resolve().parent
    # utils/paths.py -> repo root
    return Path(__file__).resolve().parent.parent


def resource_path(*parts: str) -> Path:
    """Resolve a bundled resource under the app root."""
    return app_root().joinpath(*parts)


def user_data_root() -> Path:
    override = os.environ.get("PHONE_PROCTOR_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return (base / "PhoneProctor").resolve()
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return (Path(xdg) / "phone-proctor").resolve()
    return (Path.home() / ".local" / "share" / "phone-proctor").resolve()


def writable_data_dir(*parts: str) -> Path:
    """
    Per-user writable location for journals, consent, logs.
    Never write into the frozen bundle.
    """
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    path = base / "PhoneProctor" / Path(*parts) if parts else base / "PhoneProctor"
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir() -> Path:
    path = user_data_root() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def session_data_dir() -> Path:
    path = user_data_root() / "sessions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def models_dir() -> Path:
    """Prefer bundled models; fall back to user cache for downloads."""
    bundled = install_root() / "models"
    if bundled.exists():
        return bundled
    path = user_data_root() / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def audio_dir() -> Path:
    path = user_data_root() / "audio"
    path.mkdir(parents=True, exist_ok=True)
    return path


def wal_dir() -> Path:
    path = user_data_root() / "wal"
    path.mkdir(parents=True, exist_ok=True)
    return path


def media_spool_dir() -> Path:
    path = user_data_root() / "media-spool"
    path.mkdir(parents=True, exist_ok=True)
    return path


def integrity_manifest_path() -> Path:
    return install_root() / "integrity-manifest.json"


def asset(*parts: str) -> Path:
    return resource_path("assets", *parts)


def model(*parts: str) -> Path:
    return resource_path("models", *parts)


def config_file(name: str = "settings.yaml") -> Path:
    # Prefer bundled config/; fall back to cwd for dev overrides
    bundled = resource_path("config", name)
    if bundled.is_file():
        return bundled
    local = Path.cwd() / "config" / name
    return local if local.is_file() else bundled


def yolov8_weights() -> Path:
    for candidate in (
        resource_path("yolov8n.pt"),
        resource_path("models", "yolov8n.pt"),
        Path.cwd() / "yolov8n.pt",
    ):
        if candidate.is_file():
            return candidate
    return resource_path("yolov8n.pt")


def dashboard_html() -> Path:
    for candidate in (
        asset("dashboard.html"),
        resource_path("report_template", "dashboard.html"),
    ):
        if candidate.is_file():
            return candidate
    return asset("dashboard.html")
