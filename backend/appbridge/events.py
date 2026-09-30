"""Event bus pushing state changes to the web UI via ``window.evaluate_js`` (throttled)."""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable

log = logging.getLogger(__name__)


class EventBus:
    def __init__(self, min_interval: float = 0.25):
        self._sink: Callable[[str], None] | None = None
        self._min_interval = min_interval
        self._last: dict[str, float] = {}
        self._pending: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._timer_running: set[str] = set()

    def attach(self, sink: Callable[[str], None]) -> None:
        """``sink`` receives a JS snippet to evaluate (``window.evaluate_js``)."""
        self._sink = sink

    def emit(self, event: str, payload: dict | list | None = None, throttle: bool = True) -> None:
        if not throttle:
            self._send(event, payload)
            return
        with self._lock:
            now = time.monotonic()
            last = self._last.get(event, 0)
            if now - last >= self._min_interval and event not in self._timer_running:
                self._last[event] = now
                send_now = True
            else:
                self._pending[event] = {"payload": payload}
                send_now = False
                if event not in self._timer_running:
                    self._timer_running.add(event)
                    delay = max(0.0, self._min_interval - (now - last))
                    t = threading.Timer(delay, self._flush, args=(event,))
                    t.daemon = True
                    t.start()
        if send_now:
            self._send(event, payload)

    def _flush(self, event: str) -> None:
        with self._lock:
            item = self._pending.pop(event, None)
            self._timer_running.discard(event)
            self._last[event] = time.monotonic()
        if item is not None:
            self._send(event, item["payload"])

    def _send(self, event: str, payload) -> None:
        if not self._sink:
            return
        data = json.dumps({"event": event, "payload": payload}, ensure_ascii=False)
        try:
            self._sink(f"window.__appbridgeEvent && window.__appbridgeEvent({data})")
        except Exception as e:  # noqa: BLE001 - window may be closing
            log.debug("evaluate_js failed: %s", e)
