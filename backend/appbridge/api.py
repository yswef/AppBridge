"""The ``js_api`` object exposed to the web UI through pywebview.

Every public method returns JSON-serialisable data. Failures are returned as
``{"ok": False, "error": {...}}`` rather than raised, so the UI can always show a translated
message.
"""

from __future__ import annotations

import functools
import logging
import os
import subprocess
import sys
from pathlib import Path

from . import APP_NAME, __version__, errors, logging_setup, paths, verify
from .adb import Adb
from .devices import DeviceMonitor
from .events import EventBus
from .extractor import ExtractJob
from .installer import InstallJob
from .jobs import Job, JobManager
from .library import Library
from .scanner import app_details, list_apps
from .settings import SettingsStore

log = logging.getLogger(__name__)


def api_method(fn):
    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        try:
            result = fn(self, *args, **kwargs)
            return {"ok": True, "data": result}
        except Exception as e:  # noqa: BLE001 - everything is reported to the UI
            if not isinstance(e, errors.AppBridgeError):
                log.exception("API %s failed", fn.__name__)
            else:
                log.warning("API %s: %s", fn.__name__, e)
            return {"ok": False, "error": errors.from_exception(e)}

    return wrapper


def open_in_explorer(path: Path) -> None:
    path = Path(path)
    if sys.platform == "win32":
        if path.is_file():
            subprocess.Popen(["explorer", "/select,", str(path)])
        else:
            os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class Api:
    def __init__(self, adb: Adb | None = None, settings: SettingsStore | None = None, start_monitor: bool = True):
        self._settings = settings or SettingsStore()
        self._adb = adb or Adb()
        self._events = EventBus()
        self._window = None
        self._monitor = DeviceMonitor(self._adb, on_change=self._on_devices)
        self._jobs = JobManager(on_update=self._on_job)
        self._library_obj: Library | None = None
        if start_monitor:
            self._monitor.start()

    # pywebview exposes attributes that do not start with "_" - keep internals private.

    def _attach_window(self, window) -> None:
        self._window = window
        self._events.attach(window.evaluate_js)

    def _on_devices(self, devices) -> None:
        self._events.emit("devices", [d.to_dict() for d in devices], throttle=False)

    def _on_job(self, job: Job) -> None:
        self._events.emit(f"job:{job.id}", job.to_dict())
        if job.state in ("completed", "failed", "cancelled", "paused") and job.kind in ("extract", "import"):
            self._events.emit("library", None, throttle=False)

    def _shutdown(self) -> None:
        self._monitor.stop()
        for job in self._jobs.active():
            job.request_pause()

    @property
    def _library(self) -> Library:
        if self._library_obj is None:
            self._library_obj = Library(Path(self._settings.settings.library_dir))
        return self._library_obj

    def _device(self, serial: str) -> dict:
        info = self._monitor.get(serial)
        if not info:
            try:
                self._monitor.poll_once()
            except errors.AppBridgeError:
                pass
            info = self._monitor.get(serial)
        if not info:
            raise errors.AppBridgeError("DEVICE_NOT_FOUND", serial)
        if info.state == "unauthorized":
            raise errors.AppBridgeError("DEVICE_UNAUTHORIZED", serial)
        if info.state != "device":
            raise errors.AppBridgeError("DEVICE_OFFLINE", serial)
        return info.to_dict()

    # -- app ---------------------------------------------------------------------------------

    @api_method
    def get_app_info(self):
        adb_version = ""
        if self._adb.available:
            try:
                adb_version = self._adb.version()
            except errors.AppBridgeError:
                pass
        return {
            "name": APP_NAME,
            "version": __version__,
            "adb_path": str(self._adb.path or ""),
            "adb_available": self._adb.available,
            "adb_version": adb_version,
            "data_dir": str(paths.user_data_dir()),
            "log_dir": str(paths.logs_dir()),
            "portable": paths.is_portable(),
            "platform": sys.platform,
        }

    @api_method
    def get_settings(self):
        return self._settings.as_dict()

    @api_method
    def update_settings(self, changes: dict):
        changes = dict(changes or {})
        changes.pop("library_dir", None)  # changed through choose_library_dir / set_library_dir
        self._settings.update(changes)
        return self._settings.as_dict()

    @api_method
    def choose_library_dir(self):
        folder = self._open_dialog((), folder=True)
        if not folder:
            return None
        return self._set_library_dir(folder)

    @api_method
    def set_library_dir(self, folder: str):
        return self._set_library_dir(folder)

    def _set_library_dir(self, folder: str) -> dict:
        if any(j.kind in ("extract", "import") for j in self._jobs.active()):
            raise errors.AppBridgeError("UNKNOWN", "Finish running extract/import tasks first")
        new = Library(Path(folder))  # validates we can create/open it
        if self._library_obj:
            self._library_obj.close()
        self._library_obj = new
        self._settings.update({"library_dir": str(Path(folder))})
        self._events.emit("library", None, throttle=False)
        return self._settings.as_dict()

    @api_method
    def export_logs(self):
        dest = self._save_dialog("appbridge-logs.zip", ("Zip files (*.zip)",))
        if not dest:
            return None
        logging_setup.export_logs(Path(dest))
        return str(dest)

    @api_method
    def open_path(self, path: str):
        open_in_explorer(Path(path))
        return True

    # -- devices -----------------------------------------------------------------------------

    @api_method
    def list_devices(self):
        return {
            "devices": [d.to_dict() for d in self._monitor.list()],
            "error": self._monitor.last_error,
        }

    @api_method
    def refresh_devices(self):
        self._monitor.refresh_now()
        return True

    # -- dialogs -----------------------------------------------------------------------------

    def _save_dialog(self, filename: str, file_types: tuple[str, ...]):
        if not self._window:
            return None
        import webview

        res = self._window.create_file_dialog(webview.SAVE_DIALOG, save_filename=filename, file_types=file_types)
        if not res:
            return None
        return res if isinstance(res, str) else res[0]

    def _open_dialog(self, file_types: tuple[str, ...], folder: bool = False):
        if not self._window:
            return None
        import webview

        kind = webview.FOLDER_DIALOG if folder else webview.OPEN_DIALOG
        kwargs = {} if folder else {"file_types": file_types}
        res = self._window.create_file_dialog(kind, **kwargs)
        if not res:
            return None
        return res if isinstance(res, str) else res[0]

    # -- phone apps --------------------------------------------------------------------------

    @api_method
    def list_apps(self, serial: str, include_system: bool | None = None):
        self._device(serial)
        if include_system is None:
            include_system = self._settings.settings.show_system_apps
        apps = list_apps(self._adb, serial, include_system=bool(include_system))
        in_lib = self._library.packages()
        result = []
        for a in apps:
            d = a.to_dict()
            d["in_library"] = a.package in in_lib and in_lib[a.package] >= a.version_code
            result.append(d)
        return result

    @api_method
    def app_details(self, serial: str, package: str):
        self._device(serial)
        return app_details(self._adb, serial, package)

    @api_method
    def start_extract(self, serial: str, package: str, options: dict | None = None):
        info = self._device(serial)
        options = options or {}
        for j in self._jobs.active():
            if j.kind == "extract" and j.serial == serial and j.package == package:
                return j.to_dict()
        job = ExtractJob(
            self._adb,
            self._library,
            serial,
            package,
            device_label=info.get("label") or info.get("model") or serial,
            include_obb=bool(options.get("include_obb", True)),
            include_data=bool(options.get("include_data", True)),
            device_info=info,
        )
        self._jobs.submit(job)
        return job.to_dict()

    # -- jobs --------------------------------------------------------------------------------

    @api_method
    def list_jobs(self):
        return [j.to_dict() for j in self._jobs.list()]

    @api_method
    def job_action(self, job_id: str, action: str):
        if action == "cancel":
            self._jobs.cancel(job_id)
        elif action == "pause":
            self._jobs.pause(job_id)
        elif action == "resume":
            self._jobs.resume(job_id)
        else:
            raise errors.AppBridgeError("UNKNOWN", f"unknown action {action}")
        return self._jobs.get(job_id).to_dict()

    @api_method
    def job_decide(self, job_id: str, choice: str):
        self._jobs.decide(job_id, choice)
        return True

    @api_method
    def clear_finished_jobs(self):
        self._jobs.clear_finished()
        return True

    # -- library -----------------------------------------------------------------------------

    @api_method
    def library_list(self):
        self._library.reconcile()
        return {"root": str(self._library.root), "items": self._library.list()}

    @api_method
    def library_item(self, item_id: int):
        return {"item": self._library.item(int(item_id)), "manifest": self._library.manifest(int(item_id))}

    @api_method
    def library_rename(self, item_id: int, name: str):
        return self._library.rename(int(item_id), name)

    @api_method
    def library_delete(self, item_id: int):
        item_id = int(item_id)
        if any(j.item_id == item_id for j in self._jobs.active()):
            raise errors.AppBridgeError("UNKNOWN", "The item is used by a running task")
        self._library.delete(item_id)
        return True

    @api_method
    def library_open_folder(self, item_id: int | None = None):
        path = self._library.folder(int(item_id)) if item_id is not None else self._library.root
        open_in_explorer(path)
        return str(path)

    # -- install -----------------------------------------------------------------------------

    @api_method
    def start_install(self, item_id: int, serials: list[str], options: dict | None = None):
        """Start one independent install job per phone."""
        options = options or {}
        item_id = int(item_id)
        row = self._library.item(item_id)
        if row["status"] != "complete":
            raise errors.AppBridgeError("LIBRARY_ITEM_INCOMPLETE")
        jobs = []
        for serial in serials:
            info = self._device(serial)
            per = (options.get("per_device") or {}).get(serial, {})
            job = InstallJob(
                self._adb,
                self._library,
                item_id,
                serial,
                info,
                verify=bool(options.get("verify", self._settings.settings.verify_before_install)),
                allow_downgrade=bool(per.get("allow_downgrade", options.get("allow_downgrade", False))),
                replace_incompatible=bool(per.get("replace_incompatible", False)),
                include_obb=bool(options.get("include_obb", True)),
                include_data=bool(options.get("include_data", True)),
                verifier=self._verifier,
            )
            self._jobs.submit(job)
            jobs.append(job.to_dict())
        return jobs

    _verifier = staticmethod(verify.job_verifier)

    @api_method
    def install_preflight(self, item_id: int, serials: list[str], options: dict | None = None):
        """Run the pre-install checks for each phone (version, signature, SDK, ABI, space)."""
        options = options or {}
        item_id = int(item_id)
        folder = self._library.folder(item_id)
        m = self._library.manifest(item_id)
        if not (m.get("signing") or {}).get("java_hash") and m.get("complete"):
            # items extracted by older builds or imported without signing info
            sig = verify.item_signing(folder, m)
            m["signing"] = {k: sig[k] for k in ("sha256", "scheme", "consistent", "java_hash")}
            self._library.save_manifest(folder, m)
        results = []
        for serial in serials:
            try:
                info = self._device(serial)
                results.append(
                    verify.preflight(
                        self._adb,
                        folder,
                        m,
                        serial,
                        info,
                        include_obb=bool(options.get("include_obb", True)),
                        include_data=bool(options.get("include_data", True)),
                    )
                )
            except errors.AppBridgeError as e:
                results.append(
                    {
                        "serial": serial,
                        "device_label": serial,
                        "checks": [],
                        "error": e.to_dict(),
                        "can_install": False,
                        "needs_confirmation": [],
                        "installed_version_code": None,
                        "installed_version_name": None,
                    }
                )
        return results

    @api_method
    def start_verify(self, item_id: int):
        job = verify.VerifyJob.create(self._library, int(item_id))
        self._jobs.submit(job)
        return job.to_dict()
