"""E2 low-rate JPEG snapshots + spool. Snapshots stop first under backpressure."""

from __future__ import annotations

import time

from agent.media_spool import MediaSpool


class SnapshotPublisher:
    def __init__(self, spool: MediaSpool, min_interval_s: float = 5.0) -> None:
        self.spool = spool
        self.min_interval_s = min_interval_s
        self._last = 0.0
        self.stopped = False

    def maybe_publish(self, jpeg: bytes, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        if self.stopped or self.spool.snapshots_paused:
            return False
        if now - self._last < self.min_interval_s:
            return False
        try:
            self.spool.enqueue("snapshot", jpeg, {"kind": "snapshot"})
            self._last = now
            return True
        except RuntimeError:
            self.stopped = True
            return False
