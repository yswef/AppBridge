"""Background jobs (extract / install / export / import) with progress, pause/resume and decisions."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable

from . import errors
from .adb import Adb
from .errors import AppBridgeError, CancelledError, DeviceGoneError

log = logging.getLogger(__name__)

ACTIVE_STATES = {"queued", "running", "waiting_device", "needs_decision"}
FINAL_STATES = {"completed", "failed", "cancelled"}


class Progress:
    """Byte progress with a smoothed speed and ETA."""

    def __init__(self):
        self.phase = ""
        self.done = 0
        self.total = 0
        self.current = ""
        self.files_done = 0
        self.files_total = 0
        self._samples: deque[tuple[float, int]] = deque(maxlen=40)
        self._lock = threading.Lock()

    def set_total(self, total: int, files_total: int | None = None) -> None:
        with self._lock:
            self.total = max(0, int(total))
            if files_total is not None:
                self.files_total = files_total

    def set_done(self, done: int) -> None:
        with self._lock:
            self.done = max(0, int(done))
            self._samples.append((time.monotonic(), self.done))

    def reset_speed(self) -> None:
        with self._lock:
            self._samples.clear()

    def speed(self) -> float:
        with self._lock:
            now = time.monotonic()
            samples = [s for s in self._samples if now - s[0] <= 5.0]
            if len(samples) < 2:
                return 0.0
            (t0, b0), (t1, b1) = samples[0], samples[-1]
            if t1 - t0 <= 0.2:
                return 0.0
            return max(0.0, (b1 - b0) / (t1 - t0))

    def to_dict(self) -> dict:
        sp = self.speed()
        remaining = max(0, self.total - self.done)
        eta = remaining / sp if sp > 0 else None
        return {
            "phase": self.phase,
            "done": self.done,
            "total": self.total,
            "speed": sp,
            "eta": eta,
            "current": self.current,
            "files_done": self.files_done,
            "files_total": self.files_total,
        }


class Job:
    kind = "job"

    def __init__(self, title: str = "", package: str = "", serial: str = "", device_label: str = ""):
        self.id = uuid.uuid4().hex[:12]
        self.title = title
        self.package = package
        self.serial = serial
        self.device_label = device_label
        self.item_id: int | None = None
        self.state = "queued"
        self.progress = Progress()
        self.error: dict | None = None
        self.decision: dict | None = None
        self.warnings: list[dict] = []
        self.created_at = time.time()
        self.finished_at: float | None = None
        self.result: dict | None = None
        self.resumable = True
        self.cancel_event = threading.Event()
        self._pause_requested = False
        self._decision_event = threading.Event()
        self._decision_choice: str | None = None
        self._notify: Callable[[Job], None] | None = None

    # -- helpers for subclasses --------------------------------------------------------------

    def run(self) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    def changed(self) -> None:
        if self._notify:
            self._notify(self)

    def check_cancel(self) -> None:
        if self.cancel_event.is_set():
            raise CancelledError()

    def set_phase(self, phase: str, current: str = "") -> None:
        self.progress.phase = phase
        self.progress.current = current
        self.changed()

    def warn(self, code: str, detail: str = "", **params) -> None:
        self.warnings.append(errors.describe(code, detail, **params))
        self.changed()

    def ask(self, code: str, options: list[str], detail: str = "", **params) -> str:
        """Block until the user picks one of ``options`` (or the job is cancelled)."""
        self._decision_event.clear()
        self._decision_choice = None
        self.decision = {
            "code": code,
            "options": options,
            "error": errors.describe(code, detail, **params),
            "params": params,
        }
        self.state = "needs_decision"
        self.changed()
        while not self._decision_event.wait(0.3):
            if self.cancel_event.is_set():
                self.decision = None
                raise CancelledError()
        choice = self._decision_choice or options[-1]
        self.decision = None
        self.state = "running"
        self.changed()
        if choice == "cancel":
            raise CancelledError()
        return choice

    def wait_for_device(self, adb: Adb, timeout: float = 900) -> None:
        """After a disconnect, wait for the same serial to come back, then continue."""
        self.state = "waiting_device"
        self.progress.reset_speed()
        self.changed()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.cancel_event.wait(1.5):
                raise CancelledError()
            if adb.is_connected(self.serial):
                log.info("Job %s: device %s is back", self.id, self.serial)
                time.sleep(1.0)  # let adbd settle
                self.state = "running"
                self.changed()
                return
        raise DeviceGoneError("device did not come back in time")

    def with_reconnect(self, adb: Adb, fn: Callable[[], object], attempts: int = 20):
        """Run ``fn``; on disconnect wait for the device and retry (finished work is skipped by ``fn``)."""
        for _ in range(attempts):
            try:
                return fn()
            except DeviceGoneError:
                log.warning("Job %s: device %s disconnected", self.id, self.serial)
                self.wait_for_device(adb)
        raise DeviceGoneError("too many disconnects")

    # -- control -----------------------------------------------------------------------------

    def decide(self, choice: str) -> None:
        if not self.decision or choice not in self.decision["options"]:
            raise AppBridgeError("UNKNOWN", f"invalid decision {choice}")
        self._decision_choice = choice
        self._decision_event.set()

    def request_cancel(self) -> None:
        self._pause_requested = False
        self.cancel_event.set()

    def request_pause(self) -> None:
        self._pause_requested = True
        self.cancel_event.set()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "state": self.state,
            "title": self.title,
            "package": self.package,
            "serial": self.serial,
            "device_label": self.device_label,
            "item_id": self.item_id,
            "progress": self.progress.to_dict(),
            "error": self.error,
            "decision": self.decision,
            "warnings": self.warnings,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "result": self.result,
            "resumable": self.resumable,
        }

    def _execute(self) -> None:
        self.state = "running"
        self.error = None
        self.finished_at = None
        self.changed()
        try:
            self.run()
            self.state = "completed"
        except CancelledError:
            self.state = "paused" if self._pause_requested and self.resumable else "cancelled"
        except Exception as e:  # noqa: BLE001 - reported to UI
            if not isinstance(e, AppBridgeError):
                log.exception("Job %s crashed", self.id)
            else:
                log.warning("Job %s failed: %s", self.id, e)
            self.error = errors.from_exception(e)
            self.state = "failed"
        finally:
            self.decision = None
            self.finished_at = time.time()
            self._pause_requested = False
            self.changed()


class JobManager:
    def __init__(self, on_update: Callable[[Job], None] | None = None):
        self._jobs: dict[str, Job] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()
        self.on_update = on_update
        self.listeners: list[Callable[[Job], None]] = []

    def _notify(self, job: Job) -> None:
        if self.on_update:
            self.on_update(job)
        for fn in list(self.listeners):
            try:
                fn(job)
            except Exception:  # noqa: BLE001
                log.exception("job listener failed")

    def submit(self, job: Job) -> Job:
        job._notify = self._notify
        with self._lock:
            self._jobs[job.id] = job
        self._start(job)
        return job

    def _start(self, job: Job) -> None:
        job.cancel_event.clear()
        job.state = "queued"
        t = threading.Thread(target=job._execute, name=f"{job.kind}-{job.id}", daemon=True)
        with self._lock:
            self._threads[job.id] = t
        t.start()

    def get(self, job_id: str) -> Job:
        with self._lock:
            job = self._jobs.get(job_id)
        if not job:
            raise AppBridgeError("UNKNOWN", f"no job {job_id}")
        return job

    def list(self) -> list[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)

    def active(self) -> list[Job]:
        return [j for j in self.list() if j.state in ACTIVE_STATES]

    def cancel(self, job_id: str) -> None:
        job = self.get(job_id)
        if job.state == "paused":
            job.state = "cancelled"
            job.changed()
        else:
            job.request_cancel()

    def pause(self, job_id: str) -> None:
        self.get(job_id).request_pause()

    def resume(self, job_id: str) -> Job:
        job = self.get(job_id)
        if job.state in ACTIVE_STATES:
            return job
        if not job.resumable:
            raise AppBridgeError("UNKNOWN", "job cannot be resumed")
        t = self._threads.get(job.id)
        if t and t.is_alive():
            t.join(5)
        self._start(job)
        return job

    def decide(self, job_id: str, choice: str) -> None:
        self.get(job_id).decide(choice)

    def clear_finished(self) -> None:
        with self._lock:
            for jid in [j.id for j in self._jobs.values() if j.state in FINAL_STATES]:
                self._jobs.pop(jid, None)
                self._threads.pop(jid, None)

    def wait(self, job_id: str, timeout: float = 30) -> Job:
        """Test helper: wait until the job thread ends."""
        t = self._threads.get(job_id)
        if t:
            t.join(timeout)
        return self.get(job_id)
