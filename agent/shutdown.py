"""Deterministic ordered shutdown for cameras, WebRTC, detectors, and threads."""

from __future__ import annotations

import logging
import threading
from typing import Callable, Iterable

log = logging.getLogger("agent.shutdown")

StopFn = Callable[[], None]


class ShutdownCoordinator:
    """Register stop callbacks (LIFO) and run them exactly once."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._steps: list[tuple[str, StopFn]] = []
        self._done = False
        self._errors: list[str] = []

    def register(self, name: str, fn: StopFn) -> None:
        with self._lock:
            if self._done:
                raise RuntimeError("cannot register after shutdown")
            self._steps.append((name, fn))

    @property
    def errors(self) -> list[str]:
        return list(self._errors)

    def shutdown(self, timeout_s: float = 5.0) -> None:
        del timeout_s  # reserved for future per-step timeouts
        with self._lock:
            if self._done:
                return
            self._done = True
            steps = list(reversed(self._steps))
        for name, fn in steps:
            try:
                log.info("shutdown step", extra={"step": name})
                fn()
            except Exception as exc:  # noqa: BLE001 — never abort remaining steps
                self._errors.append(f"{name}: {exc}")
                log.exception("shutdown step failed", extra={"step": name})


def join_thread(thread: threading.Thread | None, timeout: float = 2.0) -> None:
    if thread is not None and thread.is_alive() and thread is not threading.current_thread():
        thread.join(timeout=timeout)
