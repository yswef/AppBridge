"""Read display metadata (label, version, SDK levels, icon) from an APK on the PC.

Uses ``pyaxmlparser`` (a small, pure-python manifest/resources parser). Parsing is best-effort:
failures never block an extraction, they only leave the label/icon empty.
"""

from __future__ import annotations

import logging
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .fsutil import long_path

log = logging.getLogger(__name__)

logging.getLogger("pyaxmlparser").setLevel(logging.ERROR)


@dataclass
class ApkMeta:
    package: str = ""
    label: str = ""
    version_name: str = ""
    version_code: int = 0
    min_sdk: int = 0
    target_sdk: int = 0
    icon: bytes | None = None


_DENSITY_ORDER = ["xxxhdpi", "xxhdpi", "xhdpi", "hdpi", "mdpi", "ldpi", "anydpi"]


def _density_rank(path: str) -> int:
    for i, d in enumerate(_DENSITY_ORDER):
        if f"-{d}" in path:
            return i
    return len(_DENSITY_ORDER)


def _find_bitmap_icon(zf: zipfile.ZipFile, icon_path: str | None) -> bytes | None:
    """Prefer the exact icon; for adaptive (XML) icons look for a same-named bitmap in other densities."""
    names = zf.namelist()
    if icon_path and icon_path.lower().endswith((".png", ".webp")) and icon_path in names:
        return zf.read(icon_path)
    stems = []
    if icon_path:
        stems.append(Path(icon_path).stem)
    stems += ["ic_launcher", "app_icon", "icon", "ic_launcher_round"]
    for stem in stems:
        cands = [n for n in names if re.match(r"res/(mipmap|drawable)[^/]*/" + re.escape(stem) + r"\.(png|webp)$", n)]
        if not cands:
            # obfuscated resources (e.g. res/a0.png) - fall back to foreground layers is not possible here
            continue
        cands.sort(key=_density_rank)
        data = zf.read(cands[0])
        if len(data) > 64:
            return data
    return None


def read_apk_meta(path: Path) -> ApkMeta:
    meta = ApkMeta()
    try:
        from pyaxmlparser import APK

        apk = APK(long_path(path))
        meta.package = apk.package or ""
        try:
            meta.label = apk.application or ""
        except Exception:  # noqa: BLE001
            meta.label = ""
        meta.version_name = apk.version_name or ""
        try:
            meta.version_code = int(apk.version_code or 0)
        except (TypeError, ValueError):
            meta.version_code = 0
        try:
            meta.min_sdk = int(apk.get_min_sdk_version() or 0)
            meta.target_sdk = int(apk.get_target_sdk_version() or 0)
        except (TypeError, ValueError):
            pass
        icon_path = None
        try:
            icon_path = apk.get_app_icon()
        except Exception:  # noqa: BLE001
            icon_path = None
        with zipfile.ZipFile(long_path(path)) as zf:
            meta.icon = _find_bitmap_icon(zf, icon_path)
    except Exception as e:  # noqa: BLE001 - metadata is optional
        log.warning("Could not parse APK metadata from %s: %s", path, e)
    if meta.label and meta.label.startswith("@"):
        meta.label = ""
    if meta.icon and not _is_image(meta.icon):
        meta.icon = None
    return meta


def _is_image(data: bytes) -> bool:
    return data.startswith(b"\x89PNG") or (data[:4] == b"RIFF" and data[8:12] == b"WEBP")
