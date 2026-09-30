"""Listing installed apps on a device, their versions, estimated sizes and remote files."""

from __future__ import annotations

import logging
import posixpath
import re
from dataclasses import asdict, dataclass, field

from .adb import Adb, parse_stat_lines, rquote
from .errors import AppBridgeError

log = logging.getLogger(__name__)

OBB_ROOT = "/sdcard/Android/obb"
DATA_ROOT = "/sdcard/Android/data"

# Heuristic hints for "games" (Android does not expose the app category over ADB).
GAME_HINTS = (
    "game",
    "games",
    "freefire",
    "pubg",
    "tencent",
    "supercell",
    "mojang",
    "minecraft",
    "mihoyo",
    "hoyoverse",
    "garena",
    "activision",
    "gameloft",
    "ea.gp",
    "netease",
    "miniclip",
    "rovio",
    "king.",
    "roblox",
    "unity",
    "epicgames",
    "levelinfinite",
    "moonton",
    "mobile.legends",
    "callofduty",
    "clashofclans",
    "brawlstars",
    "dts.freefire",
    "krafton",
    "playrix",
    "zynga",
    "voodoo",
    "ketchapp",
    "outfit7",
    "halfbrick",
    "nianticlabs",
)


@dataclass
class PackageLine:
    package: str
    apk_path: str
    uid: int | None = None


def parse_pm_list(output: str) -> list[PackageLine]:
    """Parse ``pm list packages -f [-U]``: ``package:/data/app/.../base.apk=com.x uid:10123``."""
    result = []
    for raw in output.splitlines():
        line = raw.strip()
        if not line.startswith("package:"):
            continue
        body = line[len("package:") :]
        uid = None
        m = re.search(r"\s+uid:(\d+)$", body)
        if m:
            uid = int(m.group(1))
            body = body[: m.start()]
        if "=" not in body:
            continue
        path, pkg = body.rsplit("=", 1)
        result.append(PackageLine(pkg.strip(), path.strip(), uid))
    return result


def parse_pm_path(output: str) -> list[str]:
    return [line.strip()[len("package:") :] for line in output.splitlines() if line.strip().startswith("package:")]


@dataclass
class PackageDump:
    package: str
    version_code: int = 0
    version_name: str = ""
    min_sdk: int = 0
    target_sdk: int = 0
    code_path: str = ""
    flags: list[str] = field(default_factory=list)


_PKG_HEADER = re.compile(r"^\s{2}Package \[(?P<pkg>[^\]]+)\]")


def parse_dumpsys_packages(output: str) -> dict[str, PackageDump]:
    """Parse the ``Packages:`` section of ``dumpsys package``.

    A package can appear more than once (e.g. updated system apps, "Hidden system packages");
    the first block (the active one) wins.
    """
    result: dict[str, PackageDump] = {}
    cur: PackageDump | None = None
    in_hidden = False
    for line in output.splitlines():
        if line.startswith("Hidden system packages:"):
            in_hidden = True
            cur = None
            continue
        if line and not line.startswith(" "):
            in_hidden = line.startswith("Hidden system packages:")
            cur = None
            if not line.startswith("Packages:"):
                continue
        m = _PKG_HEADER.match(line)
        if m:
            pkg = m.group("pkg")
            if in_hidden or pkg in result:
                cur = None
            else:
                cur = PackageDump(pkg)
                result[pkg] = cur
            continue
        if cur is None:
            continue
        s = line.strip()
        if s.startswith("versionCode="):
            for token in s.split():
                k, _, v = token.partition("=")
                if k == "versionCode":
                    cur.version_code = _int(v)
                elif k == "minSdk":
                    cur.min_sdk = _int(v)
                elif k == "targetSdk":
                    cur.target_sdk = _int(v)
        elif s.startswith("versionName="):
            cur.version_name = s[len("versionName=") :]
        elif s.startswith("codePath="):
            cur.code_path = s[len("codePath=") :]
        elif s.startswith("flags=[") and not cur.flags:
            cur.flags = s[len("flags=[") :].rstrip("]").split()
    return result


def _int(v: str) -> int:
    m = re.match(r"-?\d+", v or "")
    return int(m.group(0)) if m else 0


def parse_du(output: str) -> dict[str, int]:
    """Parse ``du -sk`` output into {path: bytes}."""
    out = {}
    for line in output.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and parts[0].isdigit():
            out[parts[1].rstrip("/")] = int(parts[0]) * 1024
    return out


def looks_like_game(package: str, has_obb: bool, flags: list[str]) -> bool:
    if "IS_GAME" in flags:
        return True
    p = package.lower()
    return has_obb or any(h in p for h in GAME_HINTS)


@dataclass
class AppEntry:
    package: str
    apk_path: str
    system: bool
    game: bool
    version_name: str
    version_code: int
    apk_bytes: int
    obb_bytes: int
    data_bytes: int | None
    split: bool
    in_library: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _chunks(items: list[str], n: int):
    for i in range(0, len(items), n):
        yield items[i : i + n]


def list_apps(adb: Adb, serial: str, include_system: bool = False) -> list[AppEntry]:
    flag = "" if include_system else " -3"
    r = adb.shell(serial, f"pm list packages -f -U{flag}", timeout=60)
    lines = parse_pm_list(r.out)
    if not lines:  # very old pm without -U
        lines = parse_pm_list(adb.shell(serial, f"pm list packages -f{flag}", timeout=60).out)
    if not lines and r.rc != 0:
        raise AppBridgeError("UNKNOWN", r.text)
    dumps = parse_dumpsys_packages(adb.shell(serial, "dumpsys package packages", timeout=120).out)

    # Size of each app's code directory (base + split APKs + extracted libs).
    code_dirs = {pl.package: posixpath.dirname(pl.apk_path) for pl in lines}
    dir_sizes: dict[str, int] = {}
    user_dirs = sorted({d for d in code_dirs.values() if d.startswith("/data/app")})
    for chunk in _chunks(user_dirs, 80):
        out = adb.shell(serial, "du -sk " + " ".join(rquote(d) for d in chunk) + " 2>/dev/null", timeout=90).out
        dir_sizes.update(parse_du(out))
    apk_sizes: dict[str, int] = {}
    missing = [pl.apk_path for pl in lines if code_dirs[pl.package] not in dir_sizes]
    for chunk in _chunks(missing, 80):
        cmd = "stat -c '%s|%Y|%n' " + " ".join(rquote(p) for p in chunk) + " 2>/dev/null"
        for size, _, path in parse_stat_lines(adb.shell(serial, cmd, timeout=60).out):
            apk_sizes[path] = size

    obb_sizes = {
        posixpath.basename(k): v
        for k, v in parse_du(adb.shell(serial, f"du -sk {OBB_ROOT}/* 2>/dev/null", timeout=60).out).items()
    }

    apps = []
    for pl in lines:
        d = dumps.get(pl.package, PackageDump(pl.package))
        code_dir = code_dirs[pl.package]
        size = dir_sizes.get(code_dir) or apk_sizes.get(pl.apk_path, 0)
        obb = obb_sizes.get(pl.package, 0)
        system = "SYSTEM" in d.flags or not pl.apk_path.startswith("/data/")
        apps.append(
            AppEntry(
                package=pl.package,
                apk_path=pl.apk_path,
                system=system,
                game=looks_like_game(pl.package, obb > 0, d.flags),
                version_name=d.version_name,
                version_code=d.version_code,
                apk_bytes=size,
                obb_bytes=obb,
                data_bytes=None,
                split=False,
            )
        )
    apps.sort(key=lambda a: (-(a.apk_bytes + a.obb_bytes), a.package))
    return apps


@dataclass
class RemoteFile:
    remote: str
    size: int
    mtime: int
    rel: str  # path relative to the kind's root (posix)


def list_remote_files(adb: Adb, serial: str, root: str) -> tuple[list[RemoteFile], str | None]:
    """List all files below ``root`` with sizes. Returns (files, error_text_or_None).

    A missing directory is not an error (empty list). A permission problem returns the error text.
    """
    cmd = f"find {rquote(root)} -type f -exec stat -c '%s|%Y|%n' {{}} + 2>&1"
    r = adb.shell(serial, cmd, timeout=300)
    files: list[RemoteFile] = []
    problems = []
    prefix = root.rstrip("/") + "/"
    for line in r.out.splitlines():
        if "|" in line and line.split("|", 1)[0].isdigit():
            for size, mtime, path in parse_stat_lines(line):
                if path.startswith(prefix):
                    files.append(RemoteFile(path, size, mtime, path[len(prefix) :]))
        elif line.strip():
            problems.append(line.strip())
    denied = [p for p in problems if "Permission denied" in p or "Operation not permitted" in p]
    not_found = all("No such file" in p for p in problems) if problems else False
    if denied:
        return files, "\n".join(problems[:20])
    if problems and not not_found and not files:
        return files, "\n".join(problems[:20])
    return files, None


def package_dump(adb: Adb, serial: str, package: str) -> PackageDump | None:
    return parse_dumpsys_packages(adb.shell(serial, f"dumpsys package {rquote(package)}", timeout=60).out).get(package)


def apk_paths(adb: Adb, serial: str, package: str) -> list[str]:
    r = adb.shell(serial, f"pm path {rquote(package)}", timeout=30)
    paths = parse_pm_path(r.out)
    if not paths:
        raise AppBridgeError("PACKAGE_NOT_FOUND", r.text or package)
    return paths


def app_details(adb: Adb, serial: str, package: str) -> dict:
    """Detailed sizes for one app (APK files, OBB, Android/data) shown before extraction."""
    apks = apk_paths(adb, serial, package)
    stat_cmd = "stat -c '%s|%Y|%n' " + " ".join(rquote(p) for p in apks)
    apk_list = [{"path": p, "size": s} for s, _, p in parse_stat_lines(adb.shell(serial, stat_cmd, timeout=30).out)]
    obb_files, _ = list_remote_files(adb, serial, f"{OBB_ROOT}/{package}")
    data_files, data_err = list_remote_files(adb, serial, f"{DATA_ROOT}/{package}")
    dump = package_dump(adb, serial, package) or PackageDump(package)
    from .errors import describe

    return {
        "package": package,
        "apks": apk_list,
        "obb_bytes": sum(f.size for f in obb_files),
        "obb_files": len(obb_files),
        "data_bytes": None if data_err else sum(f.size for f in data_files),
        "data_files": None if data_err else len(data_files),
        "data_error": describe("DATA_ACCESS_DENIED", data_err) if data_err else None,
        "version_name": dump.version_name,
        "version_code": dump.version_code,
        "target_sdk": dump.target_sdk,
    }
