"""Filesystem locations used by AppBridge (bundled resources, user data, defaults)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import APP_NAME


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_root() -> Path:
    """Directory holding bundled resources (PyInstaller _MEIPASS or the repo's backend dir)."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def exe_dir() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return app_root()


def is_portable() -> bool:
    """Portable mode: a ``portable.txt`` next to the executable keeps all data beside it."""
    return (exe_dir() / "portable.txt").exists()


def user_data_dir() -> Path:
    override = os.environ.get("APPBRIDGE_DATA_DIR")
    if override:
        base = Path(override)
    elif is_portable():
        base = exe_dir() / "data"
    elif sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / APP_NAME
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_NAME.lower()
    base.mkdir(parents=True, exist_ok=True)
    return base


def logs_dir() -> Path:
    d = user_data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def default_library_dir() -> Path:
    if is_portable():
        return exe_dir() / "Library"
    docs = Path.home() / "Documents"
    return (docs if docs.exists() else Path.home()) / f"{APP_NAME} Library"


def web_dir() -> Path:
    """Built frontend (``frontend/dist`` in development, ``web`` when frozen)."""
    if is_frozen():
        return app_root() / "web"
    return app_root().parent / "frontend" / "dist"


def bundled_adb_candidates() -> list[Path]:
    exe = "adb.exe" if sys.platform == "win32" else "adb"
    return [
        app_root() / "platform-tools" / exe,
        app_root() / "vendor" / "platform-tools" / exe,
        exe_dir() / "platform-tools" / exe,
    ]
