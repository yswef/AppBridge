"""``manifest.json`` - the self-describing index stored with every library item and bundle."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from .errors import AppBridgeError
from .fsutil import long_path, safe_relpath

FORMAT = "appbridge-manifest"
FORMAT_VERSION = 1
MANIFEST_NAME = "manifest.json"
KINDS = ("apk", "obb", "data")


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def new_manifest(package: str) -> dict:
    return {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "app": "AppBridge",
        "package": package,
        "label": "",
        "display_name": "",
        "version_name": "",
        "version_code": 0,
        "min_sdk": 0,
        "target_sdk": 0,
        "created_at": now_iso(),
        "complete": False,
        "source_device": {},
        "includes": {"apk": True, "obb": False, "data": False},
        "signing": {"sha256": [], "scheme": "", "consistent": True},
        "icon": None,
        "notes": ["internal_data_not_included"],
        "remote_roots": {
            "apk": "",
            "obb": f"/sdcard/Android/obb/{package}",
            "data": f"/sdcard/Android/data/{package}",
        },
        "files": [],
    }


def file_entry(kind: str, rel: str, remote: str, size: int, sha256: str = "", mtime: int = 0) -> dict:
    return {"kind": kind, "path": rel, "remote": remote, "size": size, "sha256": sha256, "mtime": mtime}


def validate(m: dict) -> dict:
    if not isinstance(m, dict) or m.get("format") != FORMAT:
        raise AppBridgeError("INVALID_BUNDLE", "manifest format mismatch")
    if int(m.get("format_version", 0)) > FORMAT_VERSION:
        raise AppBridgeError("INVALID_BUNDLE", "manifest created by a newer AppBridge")
    if not m.get("package") or not isinstance(m.get("files"), list):
        raise AppBridgeError("INVALID_BUNDLE", "manifest missing package or files")
    for f in m["files"]:
        if f.get("kind") not in KINDS:
            raise AppBridgeError("INVALID_BUNDLE", f"bad file kind {f.get('kind')}")
        try:
            safe = safe_relpath(str(f.get("path", "")))
        except ValueError as e:
            raise AppBridgeError("INVALID_BUNDLE", str(e)) from e
        if safe != f["path"] or not safe.startswith(f["kind"] + "/"):
            raise AppBridgeError("INVALID_BUNDLE", f"unsafe path {f['path']}")
        if int(f.get("size", -1)) < 0:
            raise AppBridgeError("INVALID_BUNDLE", "bad file size")
    return m


def load(folder: Path) -> dict:
    p = Path(folder) / MANIFEST_NAME
    try:
        with open(long_path(p), encoding="utf-8") as fh:
            return validate(json.load(fh))
    except FileNotFoundError as e:
        raise AppBridgeError("FILE_MISSING", str(p)) from e
    except ValueError as e:
        raise AppBridgeError("INVALID_BUNDLE", f"{p}: {e}") from e


def save(folder: Path, m: dict) -> None:
    p = Path(folder) / MANIFEST_NAME
    tmp = Path(folder) / (MANIFEST_NAME + ".tmp")
    with open(long_path(tmp), "w", encoding="utf-8") as fh:
        json.dump(m, fh, ensure_ascii=False, indent=2)
    os.replace(long_path(tmp), long_path(p))


def total_size(m: dict) -> int:
    return sum(int(f.get("size", 0)) for f in m.get("files", []))


def apk_files(m: dict) -> list[dict]:
    files = [f for f in m["files"] if f["kind"] == "apk"]
    # base.apk first - install-multiple does not require it, but it keeps logs readable.
    return sorted(files, key=lambda f: (os.path.basename(f["path"]) != "base.apk", f["path"]))
