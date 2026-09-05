"""Laptop/phone encrypted ring buffers for evidence bundles."""

from __future__ import annotations

import hashlib
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque


@dataclass
class RingFrame:
    ts: float
    payload: bytes
    sha256: str


class RingBuffer:
    def __init__(self, duration_s: float, label: str = "laptop") -> None:
        self.duration_s = duration_s
        self.label = label
        self._lock = threading.Lock()
        self._frames: Deque[RingFrame] = deque()

    def push(self, payload: bytes, ts: float | None = None) -> None:
        ts = ts if ts is not None else time.time()
        frame = RingFrame(ts=ts, payload=payload, sha256=hashlib.sha256(payload).hexdigest())
        with self._lock:
            self._frames.append(frame)
            cutoff = ts - self.duration_s
            while self._frames and self._frames[0].ts < cutoff:
                self._frames.popleft()

    def snapshot(self, pre_s: float, post_s: float, now: float | None = None) -> list[RingFrame]:
        now = now if now is not None else time.time()
        lo, hi = now - pre_s, now + post_s
        with self._lock:
            return [f for f in self._frames if lo <= f.ts <= hi]

    def hashes(self, frames: list[RingFrame]) -> list[str]:
        return [f.sha256 for f in frames]
