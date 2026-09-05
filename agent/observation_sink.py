"""Observation sink: AI threads emit observations; they do not decide exam state.

Sampled METRICS must pass through the WAL so reconnect/replay cannot drop them.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Any, Protocol


class WalWriter(Protocol):
    def append(self, event_type: str, payload: dict[str, Any], *, priority: str = "normal") -> int:
        ...


class ObservationSink:
    def __init__(self, wal: WalWriter, metrics_every: int = 5) -> None:
        self._wal = wal
        self._metrics_every = max(1, metrics_every)
        self._lock = threading.Lock()
        self._metric_count = 0
        self._closed = False

    def emit(self, event_type: str, payload: dict[str, Any] | None = None, *, priority: str | None = None) -> int | None:
        payload = dict(payload or {})
        payload.setdefault("observed_at", time.time())
        etype = event_type.upper()
        if etype == "METRICS":
            with self._lock:
                self._metric_count += 1
                if self._metric_count % self._metrics_every != 0:
                    return None
        pri = priority or ("high" if etype in {"VIOLATION", "COMMAND_RESULT", "RECEIPT"} else "normal")
        return self._wal.append(etype, payload, priority=pri)

    def close(self) -> None:
        self._closed = True


def payload_hash(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()
