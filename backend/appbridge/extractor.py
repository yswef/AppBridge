"""Extract an installed app (APKs + OBB + Android/data) from a phone into the library."""

from __future__ import annotations

import logging
import os
import posixpath
from pathlib import Path

from . import manifest as mf
from .adb import Adb, parse_stat_lines, rquote
from .apkinfo import read_apk_meta
from .errors import AppBridgeError
from .fsutil import free_bytes, long_path
from .jobs import Job
from .library import ICON_NAME, Library
from .scanner import DATA_ROOT, OBB_ROOT, RemoteFile, apk_paths, list_remote_files, package_dump
from .transfer import Puller, PullItem, TransferState, make_items

log = logging.getLogger(__name__)

SAFETY_MARGIN = 200 * 1024 * 1024


class ExtractJob(Job):
    kind = "extract"

    def __init__(
        self,
        adb: Adb,
        library: Library,
        serial: str,
        package: str,
        device_label: str = "",
        include_obb: bool = True,
        include_data: bool = True,
        device_info: dict | None = None,
    ):
        super().__init__(title=package, package=package, serial=serial, device_label=device_label)
        self.adb = adb
        self.library = library
        self.include_obb = include_obb
        self.include_data = include_data
        self.device_info = device_info or {}
        self.folder: Path | None = None

    # -- steps -------------------------------------------------------------------------------

    def _scan(self) -> tuple[list[RemoteFile], list[RemoteFile], list[RemoteFile], dict]:
        self.set_phase("scan")
        apks = apk_paths(self.adb, self.serial, self.package)
        stat_cmd = "stat -c '%s|%Y|%n' " + " ".join(rquote(p) for p in apks)
        apk_files = [
            RemoteFile(p, s, m, posixpath.basename(p))
            for s, m, p in parse_stat_lines(self.adb.shell(self.serial, stat_cmd, timeout=30).out)
        ]
        if len(apk_files) != len(apks):
            raise AppBridgeError("PERMISSION_DENIED", "could not stat all APK files")
        dump = package_dump(self.adb, self.serial, self.package)
        info = {
            "version_code": dump.version_code if dump else 0,
            "version_name": dump.version_name if dump else "",
            "min_sdk": dump.min_sdk if dump else 0,
            "target_sdk": dump.target_sdk if dump else 0,
        }
        obb: list[RemoteFile] = []
        if self.include_obb:
            obb, err = list_remote_files(self.adb, self.serial, f"{OBB_ROOT}/{self.package}")
            if err:
                self.warn("PERMISSION_DENIED", err)
                obb = []
        data: list[RemoteFile] = []
        if self.include_data:
            while True:
                data, err = list_remote_files(self.adb, self.serial, f"{DATA_ROOT}/{self.package}")
                if not err:
                    break
                choice = self.ask("DATA_ACCESS_DENIED", ["skip_data", "retry", "cancel"], err)
                if choice == "skip_data":
                    self.include_data = False
                    data = []
                    self.warn("DATA_ACCESS_DENIED", err)
                    break
        return apk_files, obb, data, info

    def run(self) -> None:
        apk_remote, obb_remote, data_remote, info = self.with_reconnect(self.adb, self._scan)

        items = make_items("apk", apk_remote) + make_items("obb", obb_remote) + make_items("data", data_remote)
        total = sum(i.size for i in items)
        self.progress.set_total(total, len(items))

        # Reuse an unfinished extraction of the same version (resume), else a new folder.
        if self.folder is None:
            self.folder = self.library.find_incomplete(self.package, info["version_code"]) or self.library.new_folder(
                self.package, info["version_code"]
            )
        folder = self.folder
        state = TransferState(folder)
        remaining = sum(i.size for i in items if not state.is_done(i, folder))
        need = remaining + SAFETY_MARGIN
        avail = free_bytes(folder)
        if avail < need:
            raise AppBridgeError("PC_DISK_FULL", f"need {need} bytes, {avail} free", need=need, free=avail)

        m = self._base_manifest(folder, info, items)
        self.item_id = self.library.save_manifest(folder, m)
        self.changed()

        def on_failed(item: PullItem, err: AppBridgeError) -> bool:
            # Unreadable/volatile game-data files are skipped with a warning; APK/OBB must be complete.
            if item.kind == "data":
                self.warn(
                    "PERMISSION_DENIED" if err.code == "PERMISSION_DENIED" else "UNKNOWN",
                    f"{item.remote}: {err.detail}",
                )
                return True
            return False

        puller = Puller(self.adb, self, self.serial, folder, state, on_failed)
        done = 0
        for kind in ("apk", "obb", "data"):
            group = [i for i in items if i.kind == kind]
            if not group:
                continue
            self.set_phase(kind)
            puller.pull_all(group, base_done=done)
            done += sum(i.size for i in group)
        state.save()

        self.set_phase("finalize")
        skipped = {i.rel for i in puller.skipped}
        m["files"] = [
            mf.file_entry(i.kind, i.rel, i.remote, i.size, state.done[i.rel]["sha256"], i.mtime)
            for i in items
            if i.rel not in skipped
        ]
        self._fill_apk_meta(folder, m)
        self._fill_signing(folder, m)
        m["includes"] = {
            "apk": True,
            "obb": any(f["kind"] == "obb" for f in m["files"]),
            "data": any(f["kind"] == "data" for f in m["files"]),
        }
        if not self.include_data:
            m["notes"] = sorted(set(m["notes"]) | {"external_data_skipped"})
        m["complete"] = True
        self.item_id = self.library.save_manifest(folder, m)
        state.remove()
        self.result = {"item_id": self.item_id, "path": str(folder), "skipped": len(skipped)}

    # -- manifest helpers ----------------------------------------------------------------------

    def _base_manifest(self, folder: Path, info: dict, items: list[PullItem]) -> dict:
        try:
            m = mf.load(folder)
        except AppBridgeError:
            m = mf.new_manifest(self.package)
        m.update(
            {
                "version_code": info["version_code"],
                "version_name": info["version_name"],
                "min_sdk": info["min_sdk"],
                "target_sdk": info["target_sdk"],
                "complete": False,
                "source_device": {
                    "serial_hint": self.serial[-4:],
                    "model": self.device_info.get("model", ""),
                    "manufacturer": self.device_info.get("manufacturer", ""),
                    "android": self.device_info.get("android_version", ""),
                    "sdk": self.device_info.get("sdk", 0),
                    "abi": self.device_info.get("abi", ""),
                },
            }
        )
        apk_dir = posixpath.dirname(next(i.remote for i in items if i.kind == "apk"))
        m["remote_roots"]["apk"] = apk_dir
        m["files"] = [mf.file_entry(i.kind, i.rel, i.remote, i.size, "", i.mtime) for i in items]
        m.setdefault("label", "")
        return m

    def _fill_apk_meta(self, folder: Path, m: dict) -> None:
        base = folder / "apk" / "base.apk"
        if not os.path.exists(long_path(base)):
            apks = mf.apk_files(m)
            if not apks:
                return
            base = folder / apks[0]["path"]
        meta = read_apk_meta(base)
        if meta.label:
            m["label"] = meta.label
            self.title = meta.label
        m["version_name"] = m.get("version_name") or meta.version_name
        m["version_code"] = m.get("version_code") or meta.version_code
        m["min_sdk"] = m.get("min_sdk") or meta.min_sdk
        m["target_sdk"] = m.get("target_sdk") or meta.target_sdk
        if meta.icon:
            with open(long_path(folder / ICON_NAME), "wb") as fh:
                fh.write(meta.icon)
            m["icon"] = ICON_NAME

    def _fill_signing(self, folder: Path, m: dict) -> None:
        """Filled in by the verification module (signing certificates)."""
