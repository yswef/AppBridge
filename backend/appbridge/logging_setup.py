"""File logging (rotating) plus helpers for exporting logs for support."""

from __future__ import annotations

import logging
import logging.handlers
import zipfile
from pathlib import Path

from . import paths


def setup_logging(level: int = logging.INFO) -> Path:
    log_file = paths.logs_dir() / "appbridge.log"
    root = logging.getLogger()
    root.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s: %(message)s")
    fh = logging.handlers.RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    root.addHandler(sh)
    return log_file


def export_logs(dest: Path) -> Path:
    """Zip every log file into ``dest`` (logs never leave the machine unless the user sends them)."""
    dest = Path(dest)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(paths.logs_dir().glob("appbridge.log*")):
            zf.write(f, f.name)
    return dest
