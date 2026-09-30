"""Export a library item as a single ``.appbridge`` file (a zip) and import it on another PC.

* The zip holds ``manifest.json`` plus the item's files under ``apk/``, ``obb/`` and ``data/``.
* Already-compressed content (APK, OBB, images, audio, Unity bundles...) is *stored*; other
  files are deflated. Unknown extensions are sampled to decide.
* Optional splitting into fixed-size parts ``name.appbridge.001``, ``.002``... (plain byte split,
  so ``copy /b`` can also join them).
* Import validates the manifest, never trusts zip entry names (paths come from the validated
  manifest), verifies SHA-256 while extracting and cleans up on failure.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import time
import zipfile
import zlib
from pathlib import Path

from . import manifest as mf
from .errors import AppBridgeError
from .fsutil import free_bytes, long_path, rmtree
from .jobs import Job
from .library import ICON_NAME, Library

log = logging.getLogger(__name__)

EXT = ".appbridge"
CHUNK = 4 * 1024 * 1024
EXTRA_FILES = {"Install.bat", "README.txt", ICON_NAME}

STORE_EXT = {
    ".apk",
    ".obb",
    ".zip",
    ".jar",
    ".aab",
    ".apks",
    ".xapk",
    ".gz",
    ".tgz",
    ".xz",
    ".bz2",
    ".7z",
    ".rar",
    ".zst",
    ".br",
    ".lz4",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".heic",
    ".avif",
    ".ktx",
    ".ktx2",
    ".astc",
    ".pvr",
    ".etc",
    ".mp3",
    ".mp4",
    ".m4a",
    ".aac",
    ".ogg",
    ".opus",
    ".wav",
    ".webm",
    ".mkv",
    ".unity3d",
    ".bundle",
    ".assetbundle",
    ".pak",
    ".utoc",
    ".ucas",
    ".obb2",
    ".bnk",
    ".wem",
    ".usm",
    ".awb",
    ".acb",
    ".pck",
    ".dat",
    ".ab",
}


def should_store(name: str, sample: bytes) -> bool:
    ext = os.path.splitext(name.lower())[1]
    if ext in STORE_EXT:
        return True
    if len(sample) < 512:
        return False
    compressed = zlib.compress(sample, 1)
    return len(compressed) > 0.92 * len(sample)


# ---------------------------------------------------------------------------------------------
# Multi-part files
# ---------------------------------------------------------------------------------------------


class PartWriter(io.RawIOBase):
    """Write-only, non-seekable stream that rolls over to ``base.001``, ``base.002``... at ``part_size``."""

    def __init__(self, base: Path, part_size: int):
        super().__init__()
        self.base = Path(base)
        self.part_size = part_size
        self.parts: list[Path] = []
        self._fh = None
        self._in_part = 0
        self._pos = 0

    def _next(self) -> None:
        if self._fh:
            self._fh.close()
        p = Path(f"{self.base}.{len(self.parts) + 1:03d}")
        self.parts.append(p)
        self._fh = open(long_path(p), "wb")  # noqa: SIM115
        self._in_part = 0

    def writable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return False

    def tell(self) -> int:
        return self._pos

    def write(self, b) -> int:
        data = memoryview(b)
        written = 0
        while written < len(data):
            if self._fh is None or self._in_part >= self.part_size:
                self._next()
            n = min(len(data) - written, self.part_size - self._in_part)
            self._fh.write(data[written : written + n])
            self._in_part += n
            written += n
        self._pos += written
        return written

    def flush(self) -> None:
        if self._fh:
            self._fh.flush()

    def close(self) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None
        super().close()


class PartReader(io.RawIOBase):
    """Read-only seekable view over several part files as one stream."""

    def __init__(self, parts: list[Path]):
        super().__init__()
        self.parts = parts
        self.sizes = [os.path.getsize(long_path(p)) for p in parts]
        self.starts = []
        acc = 0
        for s in self.sizes:
            self.starts.append(acc)
            acc += s
        self.total = acc
        self._pos = 0
        self._handles: dict[int, object] = {}

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def seek(self, offset: int, whence: int = 0) -> int:
        if whence == 0:
            self._pos = offset
        elif whence == 1:
            self._pos += offset
        else:
            self._pos = self.total + offset
        self._pos = max(0, self._pos)
        return self._pos

    def _handle(self, i: int):
        if i not in self._handles:
            self._handles[i] = open(long_path(self.parts[i]), "rb")  # noqa: SIM115
        return self._handles[i]

    def readinto(self, b) -> int:
        view = memoryview(b)
        n = 0
        while n < len(view) and self._pos < self.total:
            i = max(j for j, s in enumerate(self.starts) if s <= self._pos)
            fh = self._handle(i)
            fh.seek(self._pos - self.starts[i])
            want = min(len(view) - n, self.sizes[i] - (self._pos - self.starts[i]))
            chunk = fh.read(want)
            if not chunk:
                break
            view[n : n + len(chunk)] = chunk
            n += len(chunk)
            self._pos += len(chunk)
        return n

    def close(self) -> None:
        for fh in self._handles.values():
            fh.close()
        self._handles.clear()
        super().close()


_PART_RE = re.compile(r"^(?P<base>.+)\.(?P<num>\d{3})$")


def resolve_parts(path: Path) -> list[Path]:
    """Given ``x.appbridge`` or any ``x.appbridge.NNN`` return the list of files forming the bundle."""
    path = Path(path)
    m = _PART_RE.match(path.name)
    if not m:
        if not path.exists():
            raise AppBridgeError("INVALID_BUNDLE", f"{path} not found")
        return [path]
    base = path.with_name(m.group("base"))
    parts = []
    i = 1
    while True:
        p = Path(f"{base}.{i:03d}")
        if not p.exists():
            break
        parts.append(p)
        i += 1
    if not parts:
        raise AppBridgeError("INVALID_BUNDLE", f"first part {base}.001 is missing")
    return parts


# ---------------------------------------------------------------------------------------------
# Install.bat
# ---------------------------------------------------------------------------------------------


def install_bat(m: dict) -> str:
    pkg = m["package"]
    if not re.fullmatch(r"[A-Za-z0-9_.]+", pkg):
        raise AppBridgeError("INVALID_BUNDLE", "unexpected package name")
    lines = [
        "@echo off",
        "setlocal EnableDelayedExpansion",
        "chcp 65001 >nul",
        'cd /d "%~dp0"',
        f"title Install {pkg}",
        "rem Simple installer created by AppBridge. Needs adb (platform-tools) next to this file or in PATH.",
        "set ADB=adb",
        'if exist "%~dp0adb.exe" set ADB="%~dp0adb.exe"',
        'if exist "%~dp0platform-tools\\adb.exe" set ADB="%~dp0platform-tools\\adb.exe"',
        "%ADB% version >nul 2>&1 || (echo adb was not found. Put adb.exe next to this file. & pause & exit /b 1)",
        "echo Waiting for a phone with USB debugging enabled...",
        "%ADB% wait-for-device",
        "set APKS=",
        'for %%F in ("apk\\*.apk") do set APKS=!APKS! "%%F"',
        "echo Installing APK files...",
        "%ADB% install-multiple -r !APKS! || (echo Installation failed. & pause & exit /b 1)",
    ]
    if any(f["kind"] == "obb" for f in m["files"]):
        lines += [
            "echo Copying OBB files...",
            f"%ADB% shell mkdir -p /sdcard/Android/obb/{pkg}",
            f'for %%F in ("obb\\*") do %ADB% push "%%F" /sdcard/Android/obb/{pkg}/',
            f'for /d %%D in ("obb\\*") do %ADB% push "%%D" /sdcard/Android/obb/{pkg}/',
        ]
    if any(f["kind"] == "data" for f in m["files"]):
        lines += [
            "echo Copying game data (Android/data)...",
            f"%ADB% shell mkdir -p /sdcard/Android/data/{pkg}",
            f'for %%F in ("data\\*") do %ADB% push "%%F" /sdcard/Android/data/{pkg}/',
            f'for /d %%D in ("data\\*") do %ADB% push "%%D" /sdcard/Android/data/{pkg}/',
        ]
    lines += ["echo Done.", "pause", ""]
    return "\r\n".join(lines)


README_TXT = """AppBridge bundle
================

EN: Open this file with AppBridge (Library > Import bundle). To install without AppBridge,
rename the file to .zip, extract it, put adb.exe next to Install.bat and run Install.bat.
Internal app data (/data/data) is not included. Share only apps you are allowed to share.

AR: افتح هذا الملف ببرنامج AppBridge (المكتبة > استيراد حزمة). للتثبيت بدون AppBridge
غيّر امتداد الملف إلى ‎.zip‎ وفك ضغطه، وضع adb.exe بجانب Install.bat ثم شغّله.
بيانات التطبيق الداخلية (/data/data) غير مضمّنة. شارك فقط التطبيقات التي يحق لك مشاركتها.
"""


# ---------------------------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------------------------


def default_bundle_name(item: dict) -> str:
    base = item.get("display_name") or item.get("label") or item["package"]
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", base).strip(" .") or item["package"]
    ver = item.get("version_name") or str(item.get("version_code") or "")
    ver = re.sub(r"[^\w.\-]", "_", ver)
    return f"{base} {ver}{EXT}".replace("  ", " ")


class ExportJob(Job):
    kind = "export"

    def __init__(self, library: Library, item_id: int, dest: Path, split_size_mb: int = 0, include_bat: bool = True):
        row = library.item(item_id)
        super().__init__(title=row["display_name"], package=row["package"])
        self.library = library
        self.item_id = item_id
        self.dest = Path(dest)
        if self.dest.suffix.lower() != EXT:
            self.dest = self.dest.with_name(self.dest.name + EXT)
        self.split_size = max(0, int(split_size_mb)) * 1024 * 1024
        self.include_bat = include_bat
        self.resumable = False

    def run(self) -> None:
        folder = self.library.folder(self.item_id)
        m = mf.load(folder)
        if not m.get("complete"):
            raise AppBridgeError("LIBRARY_ITEM_INCOMPLETE")
        total = mf.total_size(m)
        self.progress.set_total(total, len(m["files"]))
        need = total + 50 * 1024 * 1024
        avail = free_bytes(self.dest.parent)
        if avail < need:
            raise AppBridgeError("PC_DISK_FULL", f"need {need}, free {avail}", need=need, free=avail)
        self.set_phase("pack")

        split = self.split_size and total > self.split_size
        tmp = self.dest.with_name(self.dest.name + ".partial")
        writer: PartWriter | None = None
        try:
            if split:
                writer = PartWriter(tmp, self.split_size)
                zf = zipfile.ZipFile(writer, "w", allowZip64=True)
            else:
                zf = zipfile.ZipFile(long_path(tmp), "w", allowZip64=True)
            with zf:
                zf.writestr("manifest.json", _json(m), compress_type=zipfile.ZIP_DEFLATED)
                zf.writestr("README.txt", README_TXT.encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED)
                if self.include_bat:
                    zf.writestr("Install.bat", install_bat(m).encode("ascii"), compress_type=zipfile.ZIP_DEFLATED)
                icon = folder / ICON_NAME
                if m.get("icon") and os.path.exists(long_path(icon)):
                    zf.write(long_path(icon), ICON_NAME, compress_type=zipfile.ZIP_STORED)
                done = 0
                for f in m["files"]:
                    self.check_cancel()
                    self.progress.current = f["path"]
                    done = self._add(zf, folder / f["path"], f, done)
                    self.progress.files_done += 1
            if writer:
                writer.close()
                final_parts = []
                for p in writer.parts:
                    num = p.name.rsplit(".", 1)[1]
                    target = Path(f"{self.dest}.{num}")
                    os.replace(long_path(p), long_path(target))
                    final_parts.append(str(target))
            else:
                os.replace(long_path(tmp), long_path(self.dest))
                final_parts = [str(self.dest)]
        except BaseException:
            if writer:
                writer.close()
                for p in writer.parts:
                    _silent_remove(p)
            _silent_remove(tmp)
            raise
        self.result = {"files": final_parts, "size": sum(os.path.getsize(long_path(p)) for p in final_parts)}

    def _add(self, zf: zipfile.ZipFile, path: Path, f: dict, done: int) -> int:
        with open(long_path(path), "rb") as src:
            sample = src.read(65536)
            src.seek(0)
            info = zipfile.ZipInfo(f["path"], date_time=_zip_time(f.get("mtime") or time.time()))
            info.compress_type = zipfile.ZIP_STORED if should_store(f["path"], sample) else zipfile.ZIP_DEFLATED
            info.file_size = int(f["size"])
            # zip64 is chosen automatically from info.file_size (files over 4 GB)
            with zf.open(info, "w") as dst:
                while True:
                    chunk = src.read(CHUNK)
                    if not chunk:
                        break
                    dst.write(chunk)
                    done += len(chunk)
                    self.progress.set_done(done)
                    self.changed()
                    self.check_cancel()
        return done


class ImportJob(Job):
    kind = "import"

    def __init__(self, library: Library, path: Path):
        super().__init__(title=Path(path).name)
        self.library = library
        self.path = Path(path)
        self.resumable = False

    def run(self) -> None:
        self.set_phase("unpack")
        parts = resolve_parts(self.path)
        reader = PartReader(parts) if len(parts) > 1 else None
        target: Path | None = None
        try:
            try:
                zf = zipfile.ZipFile(reader if reader else long_path(parts[0]))
            except zipfile.BadZipFile as e:
                raise AppBridgeError("INVALID_BUNDLE", f"{e} (are all parts present?)") from e
            with zf:
                names = set(zf.namelist())
                if "manifest.json" not in names:
                    raise AppBridgeError("INVALID_BUNDLE", "manifest.json missing")
                try:
                    m = mf.validate(json.loads(zf.read("manifest.json").decode("utf-8")))
                except ValueError as e:
                    raise AppBridgeError("INVALID_BUNDLE", str(e)) from e
                self.package = m["package"]
                self.title = m.get("display_name") or m.get("label") or m["package"]
                missing = [f["path"] for f in m["files"] if f["path"] not in names]
                if missing:
                    raise AppBridgeError("FILE_MISSING", "\n".join(missing[:20]))
                total = mf.total_size(m)
                self.progress.set_total(total, len(m["files"]))
                avail = free_bytes(self.library.root)
                if avail < total + 100 * 1024 * 1024:
                    raise AppBridgeError("PC_DISK_FULL", f"need {total}, free {avail}", need=total, free=avail)

                target = self.library.new_folder(m["package"], int(m.get("version_code") or 0))
                done = 0
                for f in m["files"]:
                    self.check_cancel()
                    self.progress.current = f["path"]
                    done = self._extract(zf, f, target, done)
                    self.progress.files_done += 1
                if ICON_NAME in names:
                    with zf.open(ICON_NAME) as src, open(long_path(target / ICON_NAME), "wb") as dst:
                        dst.write(src.read(2_000_000))
                    m["icon"] = ICON_NAME
                else:
                    m["icon"] = None
                m["imported_at"] = mf.now_iso()
                self.item_id = self.library.save_manifest(target, m)
                self.result = {"item_id": self.item_id, "path": str(target)}
        except BaseException:
            if target is not None:
                rmtree(target)
                self.library.reconcile()
            raise
        finally:
            if reader:
                reader.close()

    def _extract(self, zf: zipfile.ZipFile, f: dict, target: Path, done: int) -> int:
        dest = target / f["path"]  # path validated by manifest.validate (no traversal)
        os.makedirs(long_path(dest.parent), exist_ok=True)
        h = hashlib.sha256()
        size = 0
        with zf.open(f["path"]) as src, open(long_path(dest), "wb") as dst:
            while True:
                chunk = src.read(CHUNK)
                if not chunk:
                    break
                dst.write(chunk)
                h.update(chunk)
                size += len(chunk)
                done += len(chunk)
                self.progress.set_done(done)
                self.changed()
                self.check_cancel()
        if size != int(f["size"]) or (f.get("sha256") and h.hexdigest() != f["sha256"]):
            raise AppBridgeError("HASH_MISMATCH", f"{f['path']}: {h.hexdigest()} != {f.get('sha256')}")
        return done


def _json(m: dict) -> bytes:
    return json.dumps(m, ensure_ascii=False, indent=2).encode("utf-8")


def _zip_time(ts: float) -> tuple:
    t = time.localtime(max(ts, 315532800))  # zip cannot store dates before 1980
    return t[:6]


def _silent_remove(p: Path) -> None:
    try:
        os.remove(long_path(p))
    except OSError:
        pass
