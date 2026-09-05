"""
Write-ahead journal for agent → central server uplink.

Batches are fsynced before send. Unacked batches are replayed on reconnect.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from utils.paths import writable_data_dir


@dataclass
class JournalBatch:
    session_id: str
    batch_id: str
    seq_no: int
    created_at: float
    payload: Dict[str, Any]
    acked: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "batch_id": self.batch_id,
            "seq_no": self.seq_no,
            "created_at": self.created_at,
            "payload": self.payload,
            "acked": self.acked,
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "JournalBatch":
        return cls(
            session_id=raw["session_id"],
            batch_id=raw["batch_id"],
            seq_no=int(raw["seq_no"]),
            created_at=float(raw["created_at"]),
            payload=raw.get("payload") or {},
            acked=bool(raw.get("acked", False)),
        )


class WriteAheadJournal:
    def __init__(self, session_id: str, base_dir: Optional[Path] = None):
        self.session_id = session_id
        self.dir = base_dir or writable_data_dir("journal", session_id)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "wal.jsonl"
        self._lock = threading.Lock()
        self._seq = self._load_max_seq() + 1

    def _load_max_seq(self) -> int:
        if not self.path.is_file():
            return 0
        max_seq = 0
        try:
            with self.path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        max_seq = max(max_seq, int(json.loads(line).get("seq_no", 0)))
                    except Exception:
                        continue
        except OSError:
            return 0
        return max_seq

    def append(self, event_type: str, data: Optional[Dict[str, Any]] = None) -> JournalBatch:
        batch = JournalBatch(
            session_id=self.session_id,
            batch_id=uuid.uuid4().hex[:12],
            seq_no=0,
            created_at=time.time(),
            payload={"type": event_type, "data": data or {}},
        )
        with self._lock:
            batch.seq_no = self._seq
            self._seq += 1
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(batch.to_dict(), separators=(",", ":")) + "\n")
                f.flush()
                os.fsync(f.fileno())
        return batch

    def iter_unacked(self) -> List[JournalBatch]:
        if not self.path.is_file():
            return []
        batches: List[JournalBatch] = []
        with self._lock:
            with self.path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        batch = JournalBatch.from_dict(json.loads(line))
                    except Exception:
                        continue
                    if not batch.acked:
                        batches.append(batch)
        return batches

    def ack(self, batch_ids: Iterable[str]) -> int:
        """Rewrite journal marking given batch_ids as acked. Returns count acked."""
        wanted = set(batch_ids)
        if not wanted or not self.path.is_file():
            return 0
        acked = 0
        with self._lock:
            lines = self.path.read_text(encoding="utf-8").splitlines()
            out: List[str] = []
            for line in lines:
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                except Exception:
                    out.append(line)
                    continue
                if raw.get("batch_id") in wanted and not raw.get("acked"):
                    raw["acked"] = True
                    acked += 1
                out.append(json.dumps(raw, separators=(",", ":")))
            tmp = self.path.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as f:
                f.write("\n".join(out) + ("\n" if out else ""))
                f.flush()
                os.fsync(f.fileno())
            tmp.replace(self.path)
        return acked

    def compact_acked(self) -> None:
        """Drop fully-acked prefix to keep journal small."""
        if not self.path.is_file():
            return
        with self._lock:
            remaining = []
            with self.path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        raw = json.loads(line)
                    except Exception:
                        remaining.append(line)
                        continue
                    if not raw.get("acked"):
                        remaining.append(json.dumps(raw, separators=(",", ":")))
            tmp = self.path.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as f:
                f.write("\n".join(remaining) + ("\n" if remaining else ""))
                f.flush()
                os.fsync(f.fileno())
            tmp.replace(self.path)
