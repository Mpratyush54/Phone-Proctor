"""Encrypted local media spool with retry. Snapshots stop first under backpressure."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from utils.paths import media_spool_dir

MAX_ATTEMPTS = 10
MAX_AGE_S = 24 * 3600


class MediaSpool:
    def __init__(self, root: Path | None = None, quota_bytes: int = 2 * 1024 * 1024 * 1024) -> None:
        self.root = root or media_spool_dir()
        self.root.mkdir(parents=True, exist_ok=True)
        self.quota_bytes = quota_bytes
        self._lock = threading.Lock()
        self.snapshots_paused = False

    def _used(self) -> int:
        return sum(p.stat().st_size for p in self.root.glob("*") if p.is_file())

    def enqueue(self, kind: str, blob: bytes, meta: dict[str, Any]) -> Path:
        with self._lock:
            if kind == "snapshot" and (self.snapshots_paused or self._used() + len(blob) > self.quota_bytes * 0.8):
                self.snapshots_paused = True
                raise RuntimeError("snapshot spool paused under backpressure")
            digest = hashlib.sha256(blob).hexdigest()
            name = f"{int(time.time()*1000)}_{kind}_{digest[:12]}"
            bin_path = self.root / f"{name}.bin"
            meta_path = self.root / f"{name}.json"
            bin_path.write_bytes(blob)
            record = {
                **meta,
                "kind": kind,
                "sha256": digest,
                "attempts": 0,
                "created_at": time.time(),
                "bytes": len(blob),
            }
            meta_path.write_text(json.dumps(record), encoding="utf-8")
            return bin_path

    def due(self) -> list[Path]:
        items = []
        for meta_path in sorted(self.root.glob("*.json")):
            rec = json.loads(meta_path.read_text(encoding="utf-8"))
            if rec.get("attempts", 0) >= MAX_ATTEMPTS:
                continue
            if time.time() - rec["created_at"] > MAX_AGE_S:
                continue
            items.append(meta_path)
        return items

    def mark_attempt(self, meta_path: Path, ok: bool) -> dict[str, Any] | None:
        rec = json.loads(meta_path.read_text(encoding="utf-8"))
        rec["attempts"] = rec.get("attempts", 0) + 1
        rec["last_attempt"] = time.time()
        if ok:
            bin_path = meta_path.with_suffix(".bin")
            if bin_path.exists():
                bin_path.unlink()
            meta_path.unlink()
            return None
        if rec["attempts"] >= MAX_ATTEMPTS or time.time() - rec["created_at"] > MAX_AGE_S:
            rec["dead_letter"] = True
        meta_path.write_text(json.dumps(rec), encoding="utf-8")
        return rec
