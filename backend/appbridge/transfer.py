"""Resumable file transfers between the device and the PC.

Pulls are grouped: large files are pulled one by one (so a resume never repeats a finished big
file), small files are pulled in batches per remote directory (thousands of small game-data
files would otherwise pay the adb start-up cost each). Every finished file is hashed and
recorded in a state file so a pause, crash or pulled cable never re-copies finished files.
"""

from __future__ import annotations

import json
import logging
import os
import posixpath
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .adb import Adb, rquote
from .errors import AppBridgeError, CancelledError, DeviceGoneError
from .fsutil import file_size, long_path, safe_relpath, sha256_file
from .jobs import Job

log = logging.getLogger(__name__)

BIG_FILE = 16 * 1024 * 1024
MAX_BATCH_FILES = 150
MAX_BATCH_CHARS = 20_000  # stay well below the Windows command-line limit (32k)
STATE_NAME = ".appbridge-state.json"


@dataclass
class PullItem:
    kind: str
    remote: str
    size: int
    mtime: int
    rel: str  # local path relative to the item folder (posix), e.g. "obb/main.1.x.obb"


class TransferState:
    """Records finished files: rel -> {size, mtime, sha256}."""

    def __init__(self, folder: Path):
        self.path = Path(folder) / STATE_NAME
        self._lock = threading.Lock()
        try:
            with open(long_path(self.path), encoding="utf-8") as fh:
                self.done: dict[str, dict] = json.load(fh).get("done", {})
        except (OSError, ValueError):
            self.done = {}

    def is_done(self, item: PullItem, folder: Path) -> bool:
        rec = self.done.get(item.rel)
        return bool(
            rec
            and rec.get("size") == item.size
            and rec.get("mtime") == item.mtime
            and file_size(Path(folder) / item.rel) == item.size
        )

    def mark(self, item: PullItem, sha256: str) -> None:
        with self._lock:
            self.done[item.rel] = {"size": item.size, "mtime": item.mtime, "sha256": sha256}

    def save(self) -> None:
        with self._lock:
            tmp = self.path.with_suffix(".tmp")
            with open(long_path(tmp), "w", encoding="utf-8") as fh:
                json.dump({"done": self.done}, fh)
            os.replace(long_path(tmp), long_path(self.path))

    def remove(self) -> None:
        try:
            os.remove(long_path(self.path))
        except OSError:
            pass


def make_items(kind: str, files, rel_root: str | None = None) -> list[PullItem]:
    """Build PullItems from scanner.RemoteFile objects under ``<kind>/``."""
    items = []
    for f in files:
        rel = safe_relpath(f"{rel_root or kind}/{f.rel}")
        items.append(PullItem(kind, f.remote, f.size, f.mtime, rel))
    return items


def _group(items: list[PullItem]) -> list[list[PullItem]]:
    groups: list[list[PullItem]] = []
    batches: dict[tuple[str, str], list[PullItem]] = {}
    for it in items:
        if it.size >= BIG_FILE:
            groups.append([it])
            continue
        key = (posixpath.dirname(it.remote), posixpath.dirname(it.rel))
        # adb pull keeps the remote basename; a sanitised local name needs its own pull
        if posixpath.basename(it.remote) != posixpath.basename(it.rel):
            groups.append([it])
            continue
        batch = batches.setdefault(key, [])
        chars = sum(len(b.remote) + 3 for b in batch)
        if len(batch) >= MAX_BATCH_FILES or chars + len(it.remote) > MAX_BATCH_CHARS:
            groups.append(batch)
            batch = batches[key] = []
        batch.append(it)
    groups.extend(b for b in batches.values() if b)
    return groups


class Puller:
    def __init__(
        self,
        adb: Adb,
        job: Job,
        serial: str,
        folder: Path,
        state: TransferState,
        on_file_failed: Callable[[PullItem, AppBridgeError], bool] | None = None,
    ):
        self.adb = adb
        self.job = job
        self.serial = serial
        self.folder = Path(folder)
        self.state = state
        # returns True to skip the file (e.g. unreadable data file), False to fail the job
        self.on_file_failed = on_file_failed
        self.completed_bytes = 0
        self.skipped: list[PullItem] = []

    def pull_all(self, items: list[PullItem], base_done: int = 0) -> None:
        job = self.job
        pending = [it for it in items if not self.state.is_done(it, self.folder)]
        already = sum(it.size for it in items) - sum(it.size for it in pending)
        self.completed_bytes = base_done + already
        job.progress.files_done += len(items) - len(pending)
        job.progress.set_done(self.completed_bytes)
        job.changed()
        try:
            for group in _group(pending):
                job.check_cancel()
                job.with_reconnect(self.adb, lambda g=group: self._pull_group(g))
                self.state.save()
        finally:
            self.state.save()

    def _pull_group(self, group: list[PullItem]) -> None:
        group = [it for it in group if not self.state.is_done(it, self.folder)]
        if not group:
            return
        local_dir = self.folder / posixpath.dirname(group[0].rel)
        os.makedirs(long_path(local_dir), exist_ok=True)
        targets = [self.folder / it.rel for it in group]
        self.job.progress.current = group[0].remote if len(group) == 1 else posixpath.dirname(group[0].remote)

        def probe() -> int:
            return sum(max(0, file_size(t)) for t in targets)

        def tick() -> None:
            self.job.progress.set_done(self.completed_bytes + min(probe(), sum(i.size for i in group)))
            self.job.changed()

        try:
            if len(group) == 1 and posixpath.basename(group[0].remote) != posixpath.basename(group[0].rel):
                # pull to the exact (sanitised) file name
                self.adb.pull(self.serial, [group[0].remote], targets[0], self.job.cancel_event, tick, probe)
            else:
                self.adb.pull(self.serial, [it.remote for it in group], local_dir, self.job.cancel_event, tick, probe)
        except (CancelledError, DeviceGoneError):
            if len(group) > 1:
                self._salvage(group)
            raise
        except OSError as e:
            raise AppBridgeError("PC_DISK_FULL" if e.errno == 28 else "UNKNOWN", str(e)) from e
        except AppBridgeError as e:
            if len(group) > 1:
                # retry one by one to isolate the unreadable file(s)
                for it in group:
                    self._pull_group([it])
                return
            if self.on_file_failed and self.on_file_failed(group[0], e):
                self.skipped.append(group[0])
                self.completed_bytes += group[0].size
                return
            raise
        self._finish(group)

    def _salvage(self, group: list[PullItem]) -> None:
        """After an interrupted batch keep the files that were already written completely.

        adb writes files sequentially without pre-allocating, so a local file whose size equals the
        remote size is complete.
        """
        for it in group:
            path = self.folder / it.rel
            if not self.state.is_done(it, self.folder) and file_size(path) == it.size:
                self.state.mark(it, sha256_file(path))
                self.completed_bytes += it.size
                self.job.progress.files_done += 1
        self.job.progress.set_done(self.completed_bytes)

    def _finish(self, group: list[PullItem]) -> None:
        for it in group:
            path = self.folder / it.rel
            got = file_size(path)
            if got != it.size:
                if not self.adb.is_connected(self.serial):
                    raise DeviceGoneError(f"incomplete file {it.remote}")
                # file changed on the device while copying (e.g. the game was running)
                if self.on_file_failed and self.on_file_failed(
                    it, AppBridgeError("UNKNOWN", f"size mismatch {it.remote}: {got} != {it.size}")
                ):
                    self.skipped.append(it)
                    self.completed_bytes += it.size
                    continue
                raise AppBridgeError("UNKNOWN", f"size mismatch for {it.remote}: {got} != {it.size}")
            self.job.progress.current = it.remote
            digest = sha256_file(path, cancel=self.job.check_cancel)
            self.state.mark(it, digest)
            self.completed_bytes += it.size
            self.job.progress.files_done += 1
            self.job.progress.set_done(self.completed_bytes)
        self.job.changed()


@dataclass
class PushItem:
    local: Path
    remote: str  # full remote file path
    size: int


def _group_push(items: list[PushItem]) -> list[list[PushItem]]:
    groups: list[list[PushItem]] = []
    batches: dict[tuple[str, str], list[PushItem]] = {}
    for it in items:
        if it.size >= BIG_FILE or it.local.name != posixpath.basename(it.remote):
            groups.append([it])
            continue
        key = (str(it.local.parent), posixpath.dirname(it.remote))
        batch = batches.setdefault(key, [])
        chars = sum(len(str(b.local)) + 3 for b in batch)
        if len(batch) >= MAX_BATCH_FILES or chars + len(str(it.local)) > MAX_BATCH_CHARS:
            groups.append(batch)
            batch = batches[key] = []
        batch.append(it)
    groups.extend(b for b in batches.values() if b)
    return groups


class Pusher:
    """Push files to the device; files already present with the right size are skipped (resume)."""

    def __init__(self, adb: Adb, job: Job, serial: str):
        self.adb = adb
        self.job = job
        self.serial = serial
        self.completed_bytes = 0

    def remote_sizes(self, root: str) -> dict[str, int]:
        from .scanner import list_remote_files

        files, _ = list_remote_files(self.adb, self.serial, root)
        return {f.remote: f.size for f in files}

    def push_all(self, items: list[PushItem], root: str, base_done: int = 0) -> None:
        self.completed_bytes = base_done
        existing = self.job.with_reconnect(self.adb, lambda: self.remote_sizes(root))
        pending = []
        for it in items:
            if existing.get(it.remote) == it.size:
                self.completed_bytes += it.size
                self.job.progress.files_done += 1
            else:
                pending.append(it)
        self.job.progress.set_done(self.completed_bytes)
        self.job.changed()
        made_dirs: set[str] = set()
        for group in _group_push(pending):
            self.job.check_cancel()
            self.job.with_reconnect(self.adb, lambda g=group: self._push_group(g, made_dirs))

    def _push_group(self, group: list[PushItem], made_dirs: set[str]) -> None:
        remote_dir = posixpath.dirname(group[0].remote)
        if remote_dir not in made_dirs:
            r = self.adb.shell(self.serial, f"mkdir -p {rquote(remote_dir)} 2>&1")
            if r.rc != 0:
                code = "PERMISSION_DENIED" if "denied" in r.text.lower() else "UNKNOWN"
                raise AppBridgeError(code, r.text)
            made_dirs.add(remote_dir)
        self.job.progress.current = group[0].remote if len(group) == 1 else remote_dir
        total = sum(i.size for i in group)
        last = {"t": 0.0, "v": 0}

        def tick() -> None:
            # For a single big file, sample the remote size about once per second.
            if len(group) == 1 and group[0].size >= BIG_FILE:
                now = time.monotonic()
                if now - last["t"] >= 1.0:
                    last["t"] = now
                    try:
                        r = self.adb.shell(self.serial, f"stat -c %s {rquote(group[0].remote)} 2>/dev/null", timeout=5)
                        last["v"] = min(total, int(r.out.strip() or 0))
                    except (AppBridgeError, ValueError):
                        pass
                self.job.progress.set_done(self.completed_bytes + last["v"])
                self.job.changed()

        if len(group) == 1 and group[0].local.name != posixpath.basename(group[0].remote):
            self.adb.push(self.serial, [group[0].local], group[0].remote, self.job.cancel_event, tick, to_file=True)
        else:
            self.adb.push(self.serial, [i.local for i in group], remote_dir, self.job.cancel_event, tick)
        self.completed_bytes += total
        self.job.progress.files_done += len(group)
        self.job.progress.set_done(self.completed_bytes)
        self.job.changed()
