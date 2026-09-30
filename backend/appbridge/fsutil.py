"""Filesystem helpers: Windows long paths, hashing, free space, safe names."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

CHUNK = 4 * 1024 * 1024


def long_path(p: Path | str) -> str:
    """Return a path usable beyond MAX_PATH on Windows (``\\\\?\\`` prefix)."""
    s = os.path.abspath(str(p))
    if sys.platform == "win32" and not s.startswith("\\\\?\\"):
        if s.startswith("\\\\"):
            return "\\\\?\\UNC\\" + s[2:]
        return "\\\\?\\" + s
    return s


def sha256_file(
    path: Path | str, on_bytes: Callable[[int], None] | None = None, cancel: Callable[[], None] | None = None
) -> str:
    h = hashlib.sha256()
    with open(long_path(path), "rb") as f:
        while True:
            chunk = f.read(CHUNK)
            if not chunk:
                break
            h.update(chunk)
            if on_bytes:
                on_bytes(len(chunk))
            if cancel:
                cancel()
    return h.hexdigest()


def file_size(path: Path | str) -> int:
    try:
        return os.stat(long_path(path)).st_size
    except OSError:
        return -1


def free_bytes(path: Path | str) -> int:
    p = Path(path)
    while not p.exists() and p.parent != p:
        p = p.parent
    return shutil.disk_usage(p).free


def rmtree(path: Path | str) -> None:
    if os.path.exists(long_path(path)):
        shutil.rmtree(long_path(path))


_WIN_BAD = re.compile(r'[<>:"|?*\x00-\x1f]')


def safe_component(name: str) -> str:
    """Make a remote file/dir name valid on Windows (rare in game data, but possible)."""
    cleaned = _WIN_BAD.sub("_", name).rstrip(" .")
    if cleaned.upper().split(".")[0] in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }:
        cleaned = "_" + cleaned
    return cleaned or "_"


def safe_relpath(rel: str) -> str:
    """Sanitize a posix relative path and refuse traversal."""
    parts = [p for p in rel.replace("\\", "/").split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise ValueError(f"unsafe path: {rel}")
    return "/".join(safe_component(p) for p in parts)


def is_within(child: Path, parent: Path) -> bool:
    try:
        Path(os.path.abspath(child)).relative_to(os.path.abspath(parent))
        return True
    except ValueError:
        return False
