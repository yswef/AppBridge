"""Device discovery: polls ``adb devices -l`` and enriches entries with props and storage."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass

from .adb import Adb, DeviceEntry, parse_df
from .errors import AppBridgeError

log = logging.getLogger(__name__)


@dataclass
class DeviceInfo:
    serial: str
    state: str
    model: str = ""
    manufacturer: str = ""
    brand: str = ""
    device: str = ""
    android_version: str = ""
    sdk: int = 0
    abi: str = ""
    abis: str = ""
    free_bytes: int | None = None
    total_bytes: int | None = None
    usb: str = ""
    label: str = ""  # model plus a short serial suffix when several identical models are attached

    def to_dict(self) -> dict:
        return asdict(self)


def free_space(adb: Adb, serial: str, path: str = "/data") -> tuple[int, int] | None:
    """Return (free, total) bytes for the filesystem holding ``path`` on the device."""
    r = adb.shell(serial, f"df -k {path}", timeout=15)
    entries = parse_df(r.out)
    if not entries:
        return None
    e = entries[-1]
    return e.avail_kb * 1024, e.total_kb * 1024


def build_info(adb: Adb, entry: DeviceEntry) -> DeviceInfo:
    info = DeviceInfo(serial=entry.serial, state=entry.state)
    info.model = entry.props.get("model", "").replace("_", " ")
    info.device = entry.props.get("device", "")
    info.usb = entry.props.get("usb", "")
    if entry.state != "device":
        return info
    props = adb.getprops(entry.serial)
    info.model = props.get("ro.product.model", info.model) or info.model
    info.manufacturer = props.get("ro.product.manufacturer", "")
    info.brand = props.get("ro.product.brand", "")
    info.android_version = props.get("ro.build.version.release", "")
    try:
        info.sdk = int(props.get("ro.build.version.sdk", "0"))
    except ValueError:
        info.sdk = 0
    info.abi = props.get("ro.product.cpu.abi", "")
    info.abis = props.get("ro.product.cpu.abilist", info.abi)
    try:
        fs = free_space(adb, entry.serial)
        if fs:
            info.free_bytes, info.total_bytes = fs
    except AppBridgeError as e:
        log.warning("df failed on %s: %s", entry.serial, e)
    return info


def assign_labels(infos: list[DeviceInfo]) -> None:
    """Give identical models a distinguishing label using the tail of their serial."""
    counts: dict[str, int] = {}
    for i in infos:
        counts[i.model or i.serial] = counts.get(i.model or i.serial, 0) + 1
    for i in infos:
        base = i.model or i.serial
        i.label = f"{base} (…{i.serial[-4:]})" if counts[base] > 1 and i.model else base


class DeviceMonitor:
    """Background thread that keeps an up-to-date list of attached devices."""

    def __init__(
        self,
        adb: Adb,
        on_change: Callable[[list[DeviceInfo]], None] | None = None,
        interval: float = 1.5,
        storage_refresh: float = 20.0,
    ):
        self.adb = adb
        self.on_change = on_change
        self.interval = interval
        self.storage_refresh = storage_refresh
        self._devices: dict[str, DeviceInfo] = {}
        self._fetched_at: dict[str, float] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_error: dict | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="device-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def refresh_now(self) -> None:
        with self._lock:
            self._fetched_at.clear()
        self._wake.set()

    def list(self) -> list[DeviceInfo]:
        with self._lock:
            return list(self._devices.values())

    def get(self, serial: str) -> DeviceInfo | None:
        with self._lock:
            return self._devices.get(serial)

    def poll_once(self) -> bool:
        """Poll adb once. Returns True when the device list changed."""
        entries = self.adb.devices()
        now = time.monotonic()
        new: dict[str, DeviceInfo] = {}
        for e in entries:
            with self._lock:
                old = self._devices.get(e.serial)
                fetched = self._fetched_at.get(e.serial, 0)
            stale = now - fetched > self.storage_refresh
            if old and old.state == e.state and not stale:
                new[e.serial] = old
                continue
            try:
                info = build_info(self.adb, e)
            except AppBridgeError as err:
                log.info("Could not query %s yet: %s", e.serial, err.code)
                info = old or DeviceInfo(serial=e.serial, state=e.state)
                info.state = e.state if err.code != "DEVICE_UNAUTHORIZED" else "unauthorized"
            new[e.serial] = info
            with self._lock:
                self._fetched_at[e.serial] = now
        assign_labels(list(new.values()))
        with self._lock:
            changed = _snapshot(new) != _snapshot(self._devices)
            self._devices = new
            for s in list(self._fetched_at):
                if s not in new:
                    del self._fetched_at[s]
        return changed

    def _loop(self) -> None:
        try:
            self.adb.start_server()
        except AppBridgeError as e:
            self.last_error = e.to_dict()
            log.error("adb start-server failed: %s", e)
        while not self._stop.is_set():
            try:
                changed = self.poll_once()
                self.last_error = None
                if changed and self.on_change:
                    self.on_change(self.list())
            except AppBridgeError as e:
                self.last_error = e.to_dict()
                log.warning("device poll failed: %s", e)
            except Exception:  # noqa: BLE001 - keep monitoring alive
                log.exception("device poll crashed")
            self._wake.wait(self.interval)
            self._wake.clear()


def _snapshot(devs: dict[str, DeviceInfo]) -> list[tuple]:
    return sorted((d.serial, d.state, d.free_bytes, d.label, d.model) for d in devs.values())
