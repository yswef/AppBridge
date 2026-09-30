"""A fake ``Adb`` that emulates devices using directories on disk (for tests)."""

from __future__ import annotations

import os
import shlex
import shutil
import threading
from pathlib import Path

from appbridge.adb import Adb, DeviceEntry, Result
from appbridge.errors import AppBridgeError, CancelledError, DeviceGoneError


class FakeDevice:
    def __init__(self, serial: str, root: Path, model: str = "Pixel 7", sdk: int = 34, state: str = "device"):
        self.serial = serial
        self.root = root
        self.model = model
        self.sdk = sdk
        self.state = state
        self.packages: dict[str, dict] = {}  # pkg -> {"apks": [remote paths], "version_code": int, ...}
        self.installed: list[tuple[list[str], list[str]]] = []
        self.deny_data_read = False
        self.deny_data_write = False
        self.free_kb = 50_000_000
        self.fail_after_pulls: int | None = None
        self.install_failure: str | None = None
        self.launched: list[str] = []
        root.mkdir(parents=True, exist_ok=True)

    def local(self, remote: str) -> Path:
        return self.root / remote.lstrip("/")

    def add_file(self, remote: str, data: bytes) -> None:
        p = self.local(remote)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)


class FakeAdb(Adb):
    def __init__(self):
        super().__init__(path=None)
        self.path = Path("fake-adb")
        self.devices_map: dict[str, FakeDevice] = {}
        self.pull_count = 0
        self.lock = threading.Lock()

    @property
    def available(self) -> bool:
        return True

    def add(self, dev: FakeDevice) -> FakeDevice:
        self.devices_map[dev.serial] = dev
        return dev

    def run(self, args, serial=None, timeout=60):
        if list(args[:1]) == ["version"]:
            return Result(0, "Android Debug Bridge version 1.0.41\n", "")
        return Result(0, "", "")

    def start_server(self):
        pass

    def devices(self):
        return [DeviceEntry(d.serial, d.state, {"model": d.model.replace(" ", "_")}) for d in self.devices_map.values()]

    def _dev(self, serial) -> FakeDevice:
        d = self.devices_map.get(serial)
        if not d or d.state != "device":
            raise DeviceGoneError(f"device '{serial}' not found")
        return d

    def getprops(self, serial):
        d = self._dev(serial)
        return {
            "ro.product.model": d.model,
            "ro.product.manufacturer": "Google",
            "ro.build.version.release": str(d.sdk - 20),
            "ro.build.version.sdk": str(d.sdk),
            "ro.product.cpu.abi": "arm64-v8a",
        }

    def shell(self, serial, command, timeout=60, check=False):
        d = self._dev(serial)
        r = self._shell(d, command)
        if check and r.rc != 0:
            raise AppBridgeError("UNKNOWN", r.text)
        return r

    # A tiny interpreter for the shell commands AppBridge issues.
    def _shell(self, d: FakeDevice, command: str) -> Result:
        argv = shlex.split(command.split(" 2>")[0].split(" ;")[0])
        cmd = argv[0]
        if command.startswith("df -k"):
            return Result(
                0, f"Filesystem 1K-blocks Used Available Use% Mounted on\n/dev/x 99999999 1 {d.free_kb} 1% /data\n", ""
            )
        if cmd == "pm" and argv[1] == "path":
            pkg = argv[-1]
            if pkg not in d.packages:
                return Result(1, "", "")
            return Result(0, "".join(f"package:{a}\n" for a in d.packages[pkg]["apks"]), "")
        if cmd == "pm" and argv[1] == "list":
            third = "-3" in argv
            lines = []
            for pkg, info in d.packages.items():
                if third and info.get("system"):
                    continue
                lines.append(f"package:{info['apks'][0]}={pkg} uid:{info.get('uid', 10100)}")
            return Result(0, "\n".join(lines) + "\n", "")
        if cmd == "dumpsys" and argv[1] == "package":
            pkg = argv[2] if len(argv) > 2 else None
            out = []
            for p, info in d.packages.items():
                if pkg not in (None, "packages") and p != pkg:
                    continue
                out.append(
                    f"  Package [{p}] (abc):\n    versionCode={info.get('version_code', 1)} minSdk=21 targetSdk=33\n"
                    f"    versionName={info.get('version_name', '1.0')}\n    flags=[ HAS_CODE ALLOW_CLEAR_USER_DATA ]\n"
                )
            return Result(0, "Packages:\n" + "".join(out), "")
        if cmd == "find":
            target = argv[1]
            if "/Android/data/" in target and d.deny_data_read:
                return Result(1, "", f"find: '{target}': Permission denied\n")
            base = d.local(target)
            if not base.exists():
                return Result(1, "", f"find: '{target}': No such file or directory\n")
            lines = []
            for p in sorted(base.rglob("*")):
                if p.is_file():
                    rel = "/" + p.relative_to(d.root).as_posix()
                    lines.append(f"{p.stat().st_size}|{int(p.stat().st_mtime)}|{rel}")
            return Result(0, "\n".join(lines) + ("\n" if lines else ""), "")
        if cmd == "ls":
            target = argv[-1]
            if "/Android/data/" in target and d.deny_data_read:
                return Result(1, "", f"ls: {target}: Permission denied\n")
            return Result(0 if d.local(target).exists() else 1, "", "")
        if cmd == "stat":
            p = d.local(argv[-1])
            if not p.exists():
                return Result(1, "", "No such file")
            return Result(0, f"{p.stat().st_size}|{int(p.stat().st_mtime)}|{argv[-1]}\n", "")
        if cmd == "du":
            total = 0
            outs = []
            for t in argv[2:]:
                p = d.local(t)
                if p.exists():
                    size = (
                        sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.is_dir() else p.stat().st_size
                    )
                    outs.append(f"{max(1, size // 1024)}\t{t}")
                    total += size
            return Result(0, "\n".join(outs) + "\n", "")
        if cmd == "mkdir":
            target = argv[-1]
            if "/Android/data/" in target and d.deny_data_write:
                return Result(1, "", f"mkdir: '{target}': Permission denied\n")
            d.local(target).mkdir(parents=True, exist_ok=True)
            return Result(0, "", "")
        if cmd in ("chmod", "am", "rm"):
            if cmd == "rm":
                shutil.rmtree(d.local(argv[-1]), ignore_errors=True)
            return Result(0, "", "")
        if cmd == "monkey":
            d.launched.append(argv[2])
            d.deny_data_write = False
            return Result(0, "Events injected: 1\n", "")
        if cmd == "pm" and argv[1] == "uninstall":
            d.packages.pop(argv[-1], None)
            return Result(0, "Success\n", "")
        return Result(0, "", "")

    def pull(self, serial, remotes, local_dir, cancel=None, on_tick=None, progress_probe=None):
        d = self._dev(serial)
        local_dir.mkdir(parents=True, exist_ok=True)
        for r in remotes:
            if cancel is not None and cancel.is_set():
                raise CancelledError()
            with self.lock:
                if d.fail_after_pulls is not None and self.pull_count >= d.fail_after_pulls:
                    d.state = "offline"
                    raise DeviceGoneError("device offline")
                self.pull_count += 1
            if "/Android/data/" in r and d.deny_data_read:
                raise AppBridgeError("PERMISSION_DENIED", "Permission denied")
            shutil.copy2(d.local(r), local_dir / os.path.basename(r))
            if on_tick:
                on_tick()

    def push(self, serial, locals_, remote_dir, cancel=None, on_tick=None):
        d = self._dev(serial)
        if "/Android/data/" in remote_dir and d.deny_data_write:
            raise AppBridgeError("PERMISSION_DENIED", "remote couldn't create file: Permission denied")
        dest = d.local(remote_dir)
        dest.mkdir(parents=True, exist_ok=True)
        for p in locals_:
            if cancel is not None and cancel.is_set():
                raise CancelledError()
            if Path(p).is_dir():
                shutil.copytree(p, dest / Path(p).name, dirs_exist_ok=True)
            else:
                shutil.copy2(p, dest / Path(p).name)
            if on_tick:
                on_tick()

    def install_multiple(self, serial, apks, flags, cancel=None, on_tick=None):
        d = self._dev(serial)
        if d.install_failure:
            fail, d.install_failure = d.install_failure, None
            return Result(1, "", f"adb: failed to finalize session\nFailure [{fail}]\n")
        d.installed.append(([str(a) for a in apks], list(flags)))
        return Result(0, "Success\n", "")
