"""The on-disk library: one folder per extracted app plus a SQLite index (``library.db``).

The folders (with their ``manifest.json``) are the source of truth; the SQLite index is a fast
cache that is reconciled with the folders on open, so a library folder can be moved or copied
to another computer and simply re-opened.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import sqlite3
import threading
from pathlib import Path

from . import manifest as mf
from .errors import AppBridgeError
from .fsutil import long_path, rmtree

log = logging.getLogger(__name__)

DB_NAME = "library.db"
ICON_NAME = "icon.png"

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folder TEXT NOT NULL UNIQUE,
    package TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    display_name TEXT NOT NULL DEFAULT '',
    version_name TEXT NOT NULL DEFAULT '',
    version_code INTEGER NOT NULL DEFAULT 0,
    min_sdk INTEGER NOT NULL DEFAULT 0,
    target_sdk INTEGER NOT NULL DEFAULT 0,
    size INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT '',
    complete INTEGER NOT NULL DEFAULT 0,
    has_obb INTEGER NOT NULL DEFAULT 0,
    has_data INTEGER NOT NULL DEFAULT 0,
    apk_count INTEGER NOT NULL DEFAULT 0,
    file_count INTEGER NOT NULL DEFAULT 0,
    signer_sha256 TEXT NOT NULL DEFAULT '[]',
    source_device TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_items_package ON items(package);
"""


def folder_name(package: str, version_code: int) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]", "_", package)[:80]
    return f"{base}-{version_code}" if version_code else base


class Library:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(self.root / DB_NAME), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        self._icon_cache: dict[str, str | None] = {}
        self.reconcile()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # -- sync with folders ------------------------------------------------------------------

    def reconcile(self) -> None:
        """Index every folder with a manifest; drop index rows whose folder vanished."""
        with self._lock:
            seen = set()
            for child in sorted(self.root.iterdir()):
                if not child.is_dir() or not (child / mf.MANIFEST_NAME).exists():
                    continue
                try:
                    m = mf.load(child)
                except AppBridgeError as e:
                    log.warning("Skipping %s: %s", child, e)
                    continue
                self._upsert(child.name, m)
                seen.add(child.name)
            for row in self._db.execute("SELECT id, folder FROM items").fetchall():
                if row["folder"] not in seen:
                    self._db.execute("DELETE FROM items WHERE id=?", (row["id"],))
            self._db.commit()

    def _upsert(self, folder: str, m: dict) -> int:
        files = m.get("files", [])
        values = {
            "folder": folder,
            "package": m["package"],
            "label": m.get("label", ""),
            "display_name": m.get("display_name", ""),
            "version_name": m.get("version_name", ""),
            "version_code": int(m.get("version_code") or 0),
            "min_sdk": int(m.get("min_sdk") or 0),
            "target_sdk": int(m.get("target_sdk") or 0),
            "size": mf.total_size(m),
            "created_at": m.get("created_at", ""),
            "complete": 1 if m.get("complete") else 0,
            "has_obb": int(any(f["kind"] == "obb" for f in files)),
            "has_data": int(any(f["kind"] == "data" for f in files)),
            "apk_count": sum(1 for f in files if f["kind"] == "apk"),
            "file_count": len(files),
            "signer_sha256": json.dumps(m.get("signing", {}).get("sha256", [])),
            "source_device": (m.get("source_device") or {}).get("model", ""),
            "notes": json.dumps(m.get("notes", [])),
        }
        cols = ", ".join(values)
        placeholders = ", ".join("?" for _ in values)
        updates = ", ".join(f"{k}=excluded.{k}" for k in values if k != "folder")
        self._db.execute(
            f"INSERT INTO items ({cols}) VALUES ({placeholders}) ON CONFLICT(folder) DO UPDATE SET {updates}",
            tuple(values.values()),
        )
        self._icon_cache.pop(folder, None)
        row = self._db.execute("SELECT id FROM items WHERE folder=?", (folder,)).fetchone()
        return int(row["id"])

    # -- item operations ---------------------------------------------------------------------

    def new_folder(self, package: str, version_code: int) -> Path:
        with self._lock:
            base = folder_name(package, version_code)
            name, n = base, 2
            while (self.root / name).exists():
                name = f"{base}_{n}"
                n += 1
            path = self.root / name
            path.mkdir(parents=True)
            return path

    def save_manifest(self, folder: Path, m: dict) -> int:
        with self._lock:
            mf.save(folder, m)
            item_id = self._upsert(Path(folder).name, m)
            self._db.commit()
            return item_id

    def find_incomplete(self, package: str, version_code: int) -> Path | None:
        with self._lock:
            row = self._db.execute(
                "SELECT folder FROM items WHERE package=? AND version_code=? AND complete=0 ORDER BY id DESC",
                (package, version_code),
            ).fetchone()
        return self.root / row["folder"] if row else None

    def packages(self) -> dict[str, int]:
        """package -> highest complete version_code present in the library."""
        with self._lock:
            rows = self._db.execute(
                "SELECT package, MAX(version_code) v FROM items WHERE complete=1 GROUP BY package"
            ).fetchall()
        return {r["package"]: r["v"] for r in rows}

    def get_row(self, item_id: int) -> sqlite3.Row:
        with self._lock:
            row = self._db.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
        if not row:
            raise AppBridgeError("FILE_MISSING", f"library item {item_id} not found")
        return row

    def folder(self, item_id: int) -> Path:
        return self.root / self.get_row(item_id)["folder"]

    def manifest(self, item_id: int) -> dict:
        return mf.load(self.folder(item_id))

    def rename(self, item_id: int, name: str) -> dict:
        name = (name or "").strip()[:120]
        folder = self.folder(item_id)
        m = mf.load(folder)
        m["display_name"] = name
        self.save_manifest(folder, m)
        return self.item(item_id)

    def delete(self, item_id: int) -> None:
        with self._lock:
            folder = self.folder(item_id)
            rmtree(folder)
            self._db.execute("DELETE FROM items WHERE id=?", (item_id,))
            self._db.commit()

    def _icon_data_url(self, folder: str) -> str | None:
        if folder in self._icon_cache:
            return self._icon_cache[folder]
        p = self.root / folder / ICON_NAME
        url = None
        try:
            with open(long_path(p), "rb") as fh:
                data = fh.read(2_000_000)
            mime = "image/webp" if data[:4] == b"RIFF" else "image/png"
            url = f"data:{mime};base64," + base64.b64encode(data).decode()
        except OSError:
            url = None
        self._icon_cache[folder] = url
        return url

    def _row_dict(self, r: sqlite3.Row) -> dict:
        return {
            "id": r["id"],
            "package": r["package"],
            "label": r["label"],
            "display_name": r["display_name"] or r["label"] or r["package"],
            "version_name": r["version_name"],
            "version_code": r["version_code"],
            "min_sdk": r["min_sdk"],
            "target_sdk": r["target_sdk"],
            "size": r["size"],
            "created_at": r["created_at"],
            "status": "complete" if r["complete"] else "incomplete",
            "path": str(self.root / r["folder"]),
            "icon": self._icon_data_url(r["folder"]),
            "has_obb": bool(r["has_obb"]),
            "has_data": bool(r["has_data"]),
            "apk_count": r["apk_count"],
            "file_count": r["file_count"],
            "signer_sha256": json.loads(r["signer_sha256"] or "[]"),
            "source_device": r["source_device"],
            "notes": json.loads(r["notes"] or "[]"),
        }

    def item(self, item_id: int) -> dict:
        return self._row_dict(self.get_row(item_id))

    def list(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM items ORDER BY created_at DESC, id DESC").fetchall()
        return [self._row_dict(r) for r in rows]
