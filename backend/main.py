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
    try:
        webview.start(
            debug=bool(os.environ.get("APPBRIDGE_DEBUG")),
            private_mode=True,
            gui="edgechromium" if sys.platform == "win32" else None,
        )
    finally:
        api._shutdown()
        api._adb.kill_server()
    return 0


if __name__ == "__main__":
    sys.exit(main())
