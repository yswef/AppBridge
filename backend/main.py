"""AppBridge entry point: starts the pywebview window hosting the React UI."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from appbridge import APP_NAME, __version__, logging_setup, paths  # noqa: E402
from appbridge.api import Api  # noqa: E402

log = logging.getLogger("appbridge")


def main() -> int:
    logging_setup.setup_logging(logging.DEBUG if os.environ.get("APPBRIDGE_DEBUG") else logging.INFO)
    log.info("%s %s starting (frozen=%s)", APP_NAME, __version__, paths.is_frozen())

    import webview

    api = Api()
    dev_url = os.environ.get("APPBRIDGE_DEV_URL")  # e.g. http://localhost:5173 during development
    index = paths.web_dir() / "index.html"
    if not dev_url and not index.exists():
        log.error("UI not built: %s is missing. Run `npm run build` in frontend/.", index)
        return 1
    window = webview.create_window(
        APP_NAME,
        url=dev_url or str(index),
        js_api=api,
        width=1280,
        height=820,
        min_size=(980, 640),
        background_color="#0f1115",
        text_select=False,
    )
    api._attach_window(window)
    window.events.closed += api._shutdown

    # Opening a .appbridge file with AppBridge (file association) imports it in one click.
    bundle_arg = next((a for a in sys.argv[1:] if ".appbridge" in a.lower() and Path(a).exists()), None)
    if bundle_arg:
        window.events.loaded += lambda: api.import_bundle(bundle_arg)
    try:
        _start(webview)
    except Exception:  # noqa: BLE001 - most often a missing WebView2 runtime
        log.exception("Could not start the window")
        _fatal(
            "AppBridge could not open its window. Install the Microsoft Edge WebView2 Runtime "
            "(https://go.microsoft.com/fwlink/p/?LinkId=2124703) and try again.\n\n"
            "تعذر على AppBridge فتح نافذته. ثبّت Microsoft Edge WebView2 Runtime ثم حاول مرة أخرى."
        )
        return 1
    finally:
        api._shutdown()
        api._adb.kill_server()
    return 0


def _start(webview) -> None:
    webview.start(
        debug=bool(os.environ.get("APPBRIDGE_DEBUG")),
        private_mode=True,
        http_server=True,  # serve the built UI over a local-only HTTP server (ES modules need it)
        gui="edgechromium" if sys.platform == "win32" else None,
    )


def _fatal(message: str) -> None:
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, APP_NAME, 0x10)
    else:
        print(message, file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
