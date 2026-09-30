"""Thin, dependency-free wrapper around the official ``adb`` binary.

All ADB work goes through :class:`Adb`, which runs the bundled ``platform-tools`` binary with
``subprocess`` and parses its textual output. Parsers are plain functions so they can be unit
tested with recorded output.
"""

from __future__ import annotations

import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from . import errors, paths
from .errors import AppBridgeError, CancelledError, DeviceGoneError

log = logging.getLogger(__name__)

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


# --------------------------------------------------------------------------------------------
# Parsers
# --------------------------------------------------------------------------------------------


@dataclass
class DeviceEntry:
    serial: str
    state: str  # device | unauthorized | offline | recovery | sideload | no permissions ...
    props: dict[str, str] = field(default_factory=dict)


_DEVICE_LINE = re.compile(r"^(?P<serial>\S+)\s+(?P<state>no permissions.*?|\S+)(?:\s+(?P<rest>.*))?$")


def parse_devices(output: str) -> list[DeviceEntry]:
    """Parse ``adb devices -l`` output."""
    result: list[DeviceEntry] = []
    for raw in output.splitlines():
        line = raw.strip()
        if not line or line.startswith("List of devices") or line.startswith("*"):
            continue
        if line.startswith("adb server") or line.startswith("daemon"):
            continue
        m = _DEVICE_LINE.match(line)
        if not m:
            continue
        state = m.group("state")
        rest = m.group("rest") or ""
        if state.startswith("no permissions"):
            state = "no permissions"
        props: dict[str, str] = {}
        for token in rest.split():
            if ":" in token:
                k, v = token.split(":", 1)
                props[k] = v
        result.append(DeviceEntry(serial=m.group("serial"), state=state, props=props))
    return result


_GETPROP_LINE = re.compile(r"^\[(?P<key>[^\]]+)\]:\s*\[(?P<value>.*)\]$")


def parse_getprop(output: str) -> dict[str, str]:
    props: dict[str, str] = {}
    for line in output.splitlines():
        m = _GETPROP_LINE.match(line.strip())
        if m:
            props[m.group("key")] = m.group("value")
    return props


@dataclass
class DfEntry:
    filesystem: str
    total_kb: int
    used_kb: int
    avail_kb: int
    mount: str


def parse_df(output: str) -> list[DfEntry]:
    """Parse ``df -k`` output (toybox). Handles wrapped lines for long filesystem names."""
    entries: list[DfEntry] = []
    pending = ""
    for raw in output.splitlines():
        line = raw.strip()
        if not line or line.lower().startswith("filesystem"):
            continue
        parts = (pending + " " + line).split() if pending else line.split()
        if len(parts) < 6:
            pending = " ".join(parts)
            continue
        pending = ""
        try:
            total, used, avail = int(parts[1]), int(parts[2]), int(parts[3])
        except ValueError:
            continue
        entries.append(DfEntry(parts[0], total, used, avail, " ".join(parts[5:])))
    return entries


def parse_stat_lines(output: str) -> list[tuple[int, int, str]]:
    """Parse lines produced by ``stat -c '%s|%Y|%n'``: (size, mtime, path)."""
    result = []
    for line in output.splitlines():
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        try:
            result.append((int(parts[0]), int(parts[1]), parts[2]))
        except ValueError:
            continue
    return result


def rquote(path: str) -> str:
    """Quote a path for the remote (device) shell."""
    return shlex.quote(path)


# --------------------------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------------------------


@dataclass
class Result:
    rc: int
    out: str
    err: str

    @property
    def text(self) -> str:
        return (self.out + "\n" + self.err).strip()


TickFn = Callable[[], None]


def find_adb() -> Path | None:
    env = os.environ.get("APPBRIDGE_ADB")
    if env and Path(env).exists():
        return Path(env)
    for cand in paths.bundled_adb_candidates():
        if cand.exists():
            return cand
    found = shutil.which("adb")
    return Path(found) if found else None


class Adb:
    def __init__(self, path: Path | str | None = None):
        p = Path(path) if path else find_adb()
        self.path = p
        self._server_lock = threading.Lock()

    # -- basics ------------------------------------------------------------------------------

    @property
    def available(self) -> bool:
        return bool(self.path and Path(self.path).exists())

    def _cmd(self, args: Sequence[str], serial: str | None) -> list[str]:
        if not self.available:
            raise AppBridgeError("ADB_NOT_FOUND")
        base = [str(self.path)]
        if serial:
            base += ["-s", serial]
        return base + [str(a) for a in args]

    def run(self, args: Sequence[str], serial: str | None = None, timeout: float = 60) -> Result:
        cmd = self._cmd(args, serial)
        log.debug("adb %s", " ".join(cmd[1:]))
        try:
            cp = subprocess.run(
                cmd,
                capture_output=True,
                timeout=timeout,
                creationflags=_NO_WINDOW,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired as e:
            raise AppBridgeError("ADB_TIMEOUT", " ".join(cmd[1:])) from e
        except FileNotFoundError as e:
            raise AppBridgeError("ADB_NOT_FOUND", str(e)) from e
        out = cp.stdout.decode("utf-8", errors="replace")
        err = cp.stderr.decode("utf-8", errors="replace")
        return Result(cp.returncode, out, err)

    def start_server(self) -> None:
        with self._server_lock:
            self.run(["start-server"], timeout=30)

    def kill_server(self) -> None:
        try:
            self.run(["kill-server"], timeout=10)
        except AppBridgeError:
            pass

    def version(self) -> str:
        r = self.run(["version"], timeout=15)
        first = r.out.splitlines()[0] if r.out else ""
        return first.strip()

    def devices(self) -> list[DeviceEntry]:
        r = self.run(["devices", "-l"], timeout=15)
        return parse_devices(r.out)

    def shell(self, serial: str, command: str, timeout: float = 60, check: bool = False) -> Result:
        """Run a command in the device shell. Raises :class:`DeviceGoneError` if the device vanished."""
        r = self.run(["shell", command], serial=serial, timeout=timeout)
        if r.rc != 0 and errors.is_device_gone(r.err or r.out):
            raise DeviceGoneError(r.text)
        if r.rc != 0 and errors.classify(r.err) == "DEVICE_UNAUTHORIZED":
            raise AppBridgeError("DEVICE_UNAUTHORIZED", r.text)
        if check and r.rc != 0:
            raise AppBridgeError(errors.classify(r.text), r.text)
        return r

    def getprops(self, serial: str) -> dict[str, str]:
        return parse_getprop(self.shell(serial, "getprop", timeout=20).out)

    def is_connected(self, serial: str) -> bool:
        try:
            return any(d.serial == serial and d.state == "device" for d in self.devices())
        except AppBridgeError:
            return False

    # -- long running transfers --------------------------------------------------------------

    def run_long(
        self,
        args: Sequence[str],
        serial: str | None,
        cancel: threading.Event | None = None,
        on_tick: TickFn | None = None,
        tick_interval: float = 0.3,
        stall_timeout: float | None = None,
        progress_probe: Callable[[], int] | None = None,
    ) -> Result:
        """Run a long adb command, polling ``on_tick`` and honouring ``cancel``.

        ``stall_timeout`` aborts the process when ``progress_probe`` (e.g. bytes written) does not
        change for that many seconds - protects against adb hanging after the cable is pulled.
        """
        cmd = self._cmd(args, serial)
        log.info("adb %s", " ".join(cmd[1:])[:500])
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            creationflags=_NO_WINDOW,
        )
        out_chunks: list[bytes] = []
        err_chunks: list[bytes] = []

        def _drain(stream, sink):
            for chunk in iter(lambda: stream.read(4096), b""):
                sink.append(chunk)

        t_out = threading.Thread(target=_drain, args=(proc.stdout, out_chunks), daemon=True)
        t_err = threading.Thread(target=_drain, args=(proc.stderr, err_chunks), daemon=True)
        t_out.start()
        t_err.start()
        last_value = None
        last_change = time.monotonic()
        stalled = False
        try:
            while True:
                try:
                    proc.wait(timeout=tick_interval)
                    break
                except subprocess.TimeoutExpired:
                    pass
                if cancel is not None and cancel.is_set():
                    proc.kill()
                    proc.wait()
                    raise CancelledError()
                if on_tick:
                    on_tick()
                if stall_timeout and progress_probe:
                    v = progress_probe()
                    if v != last_value:
                        last_value, last_change = v, time.monotonic()
                    elif time.monotonic() - last_change > stall_timeout:
                        stalled = True
                        proc.kill()
                        proc.wait()
                        break
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            t_out.join(2)
            t_err.join(2)
        out = b"".join(out_chunks).decode("utf-8", errors="replace")
        err = b"".join(err_chunks).decode("utf-8", errors="replace")
        if on_tick:
            on_tick()
        if stalled:
            if serial and not self.is_connected(serial):
                raise DeviceGoneError("transfer stalled and device disappeared")
            raise AppBridgeError("ADB_TIMEOUT", "transfer stalled")
        return Result(proc.returncode or 0, out, err)

    def _check_transfer(self, r: Result, serial: str) -> None:
        if r.rc == 0:
            return
        text = r.text
        if errors.is_device_gone(text) or not self.is_connected(serial):
            raise DeviceGoneError(text)
        code = errors.classify(text, default="UNKNOWN")
        if "Permission denied" in text:
            raise AppBridgeError("PERMISSION_DENIED", text)
        raise AppBridgeError(code, text)

    def pull(
        self,
        serial: str,
        remotes: Sequence[str],
        dest: Path,
        cancel: threading.Event | None = None,
        on_tick: TickFn | None = None,
        progress_probe: Callable[[], int] | None = None,
    ) -> None:
        """Pull ``remotes`` into directory ``dest`` (or to file ``dest`` for a single remote)."""
        if len(remotes) > 1 or dest.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
        r = self.run_long(
            ["pull", "-a", *remotes, str(dest)],
            serial,
            cancel,
            on_tick,
            stall_timeout=120 if progress_probe else None,
            progress_probe=progress_probe,
        )
        self._check_transfer(r, serial)

    def push(
        self,
        serial: str,
        locals_: Sequence[Path],
        remote_dir: str,
        cancel: threading.Event | None = None,
        on_tick: TickFn | None = None,
        to_file: bool = False,
    ) -> None:
        """Push files into ``remote_dir`` (or to the exact remote file path when ``to_file``)."""
        dest = remote_dir if to_file else remote_dir.rstrip("/") + "/"
        r = self.run_long(["push", *[str(p) for p in locals_], dest], serial, cancel, on_tick)
        self._check_transfer(r, serial)

    def install_multiple(
        self,
        serial: str,
        apks: Sequence[Path],
        flags: Sequence[str],
        cancel: threading.Event | None = None,
        on_tick: TickFn | None = None,
    ) -> Result:
        verb = "install-multiple" if len(apks) > 1 else "install"
        r = self.run_long([verb, *flags, *[str(p) for p in apks]], serial, cancel, on_tick)
        if r.rc != 0 and (errors.is_device_gone(r.text) and not self.is_connected(serial)):
            raise DeviceGoneError(r.text)
        return r
