"""Install a library item on a phone: APKs (install-multiple), then OBB, then Android/data.

Each target phone runs its own :class:`InstallJob` in its own thread, so a failure on one phone
never stops the others.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from . import errors
from . import manifest as mf
from .adb import Adb, rquote
from .devices import free_space
from .errors import AppBridgeError
from .jobs import Job
from .library import Library
from .scanner import DATA_ROOT, OBB_ROOT, package_dump
from .transfer import Pusher, PushItem

log = logging.getLogger(__name__)

# install-multiple streams the APKs to a staging session and then extracts native libraries,
# so it needs roughly twice the APK size free on /data.
APK_SPACE_FACTOR = 2.2
SPACE_MARGIN = 300 * 1024 * 1024


class InstallJob(Job):
    kind = "install"
    launch_wait_seconds = 8

    def __init__(
        self,
        adb: Adb,
        library: Library,
        item_id: int,
        serial: str,
        device: dict,
        verify: bool = True,
        allow_downgrade: bool = False,
        replace_incompatible: bool = False,
        include_obb: bool = True,
        include_data: bool = True,
        verifier=None,
    ):
        row = library.item(item_id)
        super().__init__(
            title=row["display_name"],
            package=row["package"],
            serial=serial,
            device_label=device.get("label") or device.get("model") or serial,
        )
        self.adb = adb
        self.library = library
        self.item_id = item_id
        self.device = device
        self.verify = verify
        self.allow_downgrade = allow_downgrade
        self.replace_incompatible = replace_incompatible
        self.include_obb = include_obb
        self.include_data = include_data
        self.verifier = verifier  # callable(folder, manifest, job) -> None, raises on mismatch
        self._installed = False

    # -- helpers -----------------------------------------------------------------------------

    def _sh(self, cmd: str, timeout: float = 60):
        return self.adb.shell(self.serial, cmd, timeout=timeout)

    def _check_space(self, m: dict) -> None:
        apk = sum(f["size"] for f in m["files"] if f["kind"] == "apk")
        rest = sum(f["size"] for f in m["files"] if f["kind"] != "apk" and self._wanted(f["kind"]))
        need = int(apk * APK_SPACE_FACTOR) + rest + SPACE_MARGIN
        fs = free_space(self.adb, self.serial)
        if fs and fs[0] < need:
            raise AppBridgeError("DEVICE_STORAGE_FULL", f"need {need} bytes, {fs[0]} free", need=need, free=fs[0])

    def _wanted(self, kind: str) -> bool:
        return kind == "apk" or (kind == "obb" and self.include_obb) or (kind == "data" and self.include_data)

    # -- steps -------------------------------------------------------------------------------

    def run(self) -> None:
        folder = self.library.folder(self.item_id)
        m = mf.load(folder)
        if not m.get("complete"):
            raise AppBridgeError("LIBRARY_ITEM_INCOMPLETE")
        files = [f for f in m["files"] if self._wanted(f["kind"])]
        total = sum(f["size"] for f in files)
        self.progress.set_total(total, len(files))

        if self.verify and self.verifier:
            self.set_phase("verify")
            self.verifier(folder, m, self)
            self.progress.set_done(0)
            self.progress.files_done = 0
            self.progress.reset_speed()

        self.set_phase("checks")
        self.with_reconnect(self.adb, lambda: self._check_space(m))

        apk_bytes = sum(f["size"] for f in files if f["kind"] == "apk")
        if not self._installed:
            self.with_reconnect(self.adb, lambda: self._install_apks(folder, m))
            self._installed = True
        self.progress.files_done = sum(1 for f in files if f["kind"] == "apk")
        self.progress.set_done(apk_bytes)
        self.changed()

        done = apk_bytes
        for kind, root, phase in (("obb", OBB_ROOT, "push_obb"), ("data", DATA_ROOT, "push_data")):
            group = [f for f in files if f["kind"] == kind]
            if not group:
                continue
            self.set_phase(phase)
            self._push_kind(folder, m, kind, f"{root}/{m['package']}", group, done)
            done += sum(f["size"] for f in group)

        self.set_phase("finalize")
        dump = package_dump(self.adb, self.serial, m["package"])
        self.progress.set_done(total)
        self.result = {
            "installed_version_code": dump.version_code if dump else None,
            "installed_version_name": dump.version_name if dump else None,
        }

    def _install_apks(self, folder: Path, m: dict) -> None:
        self.set_phase("install")
        apks = [folder / f["path"] for f in mf.apk_files(m)]
        flags = ["-r"]
        if self.allow_downgrade:
            flags.append("-d")
        sdk = int(self.device.get("sdk") or 0)
        bypass_added = False
        uninstalled = False
        if self.replace_incompatible:
            self._uninstall(m["package"])
            uninstalled = True
        for _attempt in range(4):
            self.check_cancel()
            r = self.adb.install_multiple(self.serial, apks, flags, self.cancel_event, self.changed)
            text = r.text
            if r.rc == 0 and "Failure" not in text:
                log.info("Installed %s on %s", m["package"], self.serial)
                return
            code = errors.classify(text, default="INSTALL_FAILED")
            log.warning("install on %s failed: %s", self.serial, text.strip()[-300:])
            if code == "INSTALL_FAILED_DEPRECATED_SDK_VERSION" and sdk >= 34 and not bypass_added:
                flags.append("--bypass-low-target-sdk-block")
                bypass_added = True
                self.warn("INSTALL_FAILED_DEPRECATED_SDK_VERSION", text)
                continue
            if code in ("INSTALL_FAILED_VERSION_DOWNGRADE", "INSTALL_FAILED_UPDATE_INCOMPATIBLE") and not uninstalled:
                choice = self.ask(code, ["uninstall_first", "cancel"], text)
                if choice == "uninstall_first":
                    self._uninstall(m["package"])
                    uninstalled = True
                    continue
            raise AppBridgeError(code, text)
        raise AppBridgeError("INSTALL_FAILED", "too many attempts")

    def _uninstall(self, package: str) -> None:
        r = self._sh(f"pm uninstall {rquote(package)}", timeout=120)
        log.info("uninstall %s on %s: %s", package, self.serial, r.text)

    def _push_kind(self, folder: Path, m: dict, kind: str, remote_root: str, files: list[dict], base: int) -> None:
        items = []
        for f in files:
            rel = f["path"][len(kind) + 1 :]
            # Keep the original remote relative path (names may have been sanitised on Windows).
            original_root = (m.get("remote_roots") or {}).get(kind, "")
            remote_rel = (
                f["remote"][len(original_root) + 1 :]
                if original_root and f["remote"].startswith(original_root + "/")
                else rel
            )
            items.append(PushItem(folder / f["path"], f"{remote_root}/{remote_rel}", f["size"]))
        pusher = Pusher(self.adb, self, self.serial)
        launched = False
        while True:
            try:
                pusher.push_all(items, remote_root, base_done=base)
                break
            except AppBridgeError as e:
                if e.code != "PERMISSION_DENIED":
                    raise
                if not launched:
                    # Fallback: open the app once so Android creates its folder with the right owner.
                    self._launch_once(m["package"])
                    launched = True
                    continue
                code = "DATA_WRITE_DENIED"
                if kind == "data":
                    choice = self.ask(code, ["retry", "skip_data", "cancel"], e.detail)
                    if choice == "skip_data":
                        self.warn(code, e.detail)
                        return
                    continue
                raise AppBridgeError(code, e.detail) from e
        # Best effort: make pushed files readable by the app on older Android versions.
        self._sh(f"chmod -R ug+rwX,o+rX {rquote(remote_root)} 2>/dev/null", timeout=120)

    def _launch_once(self, package: str) -> None:
        self.set_phase("launch")
        self._sh(f"monkey -p {rquote(package)} -c android.intent.category.LAUNCHER 1 2>&1", timeout=30)
        for _ in range(self.launch_wait_seconds):
            if self.cancel_event.wait(1):
                break
        self._sh(f"am force-stop {rquote(package)}", timeout=20)
        time.sleep(0.5)
