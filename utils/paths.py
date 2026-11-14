"""Frozen-safe filesystem roots for logs, models, and session data.

In a PyInstaller/cx_Freeze bundle, ``sys.frozen`` is set and assets live next
to the executable rather than the source tree. Callers must not write into the
install prefix; mutable data always goes under the user data directory.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def install_root() -> Path:
    """Read-only install / source root (never write here in product mode)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


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
