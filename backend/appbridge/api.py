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

from . import APP_NAME, __version__, errors, logging_setup, paths
from .adb import Adb
from .devices import DeviceMonitor
from .events import EventBus
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
        if start_monitor:
            self._monitor.start()

    # pywebview exposes attributes that do not start with "_" - keep internals private.

    def _attach_window(self, window) -> None:
        self._window = window
        self._events.attach(window.evaluate_js)

    def _on_devices(self, devices) -> None:
        self._events.emit("devices", [d.to_dict() for d in devices], throttle=False)

    def _shutdown(self) -> None:
        self._monitor.stop()

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
        self._settings.update(changes or {})
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
