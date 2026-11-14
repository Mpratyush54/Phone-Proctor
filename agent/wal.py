"""SQLite / segmented WAL with ordered sender, crash-safe ACK, and quotas.

Status is pending | acked | rejected. Cumulative contiguous ACK only.
Priority never drops violations or receipts.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 1
EVENT_QUOTA_BYTES = 512 * 1024 * 1024
MEDIA_QUOTA_BYTES = 2 * 1024 * 1024 * 1024
PROTECTED = frozenset({"VIOLATION", "COMMAND_RESULT", "RECEIPT", "NACK"})


class QuotaExceeded(Exception):
    pass


class EventWal:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._init()

    def _init(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS wal_event (
                seq_no INTEGER PRIMARY KEY,
                batch_id TEXT NOT NULL,
                schema_version INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('pending','acked','rejected')),
                priority TEXT NOT NULL,
                bytes INTEGER NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS wal_meta (
                k TEXT PRIMARY KEY,
                v TEXT NOT NULL
            );
            INSERT OR IGNORE INTO wal_meta(k, v) VALUES ('next_seq', '1');
            INSERT OR IGNORE INTO wal_meta(k, v) VALUES ('acked_through', '0');
            """
        )
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _used_bytes(self, conn: sqlite3.Connection) -> int:
        row = conn.execute(
            "SELECT COALESCE(SUM(bytes),0) FROM wal_event WHERE status != 'acked'"
        ).fetchone()
        return int(row[0])

    def append(self, event_type: str, payload: dict[str, Any], *, priority: str = "normal") -> int:
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()
        size = len(blob.encode("utf-8"))
        etype = event_type.upper()
        if etype in PROTECTED:
            priority = "high"
        with self._lock:
            used = self._used_bytes(self._conn)
            if used + size > EVENT_QUOTA_BYTES and etype not in PROTECTED:
                raise QuotaExceeded("event WAL quota 512MB exceeded")
            next_seq = int(self._conn.execute("SELECT v FROM wal_meta WHERE k='next_seq'").fetchone()[0])
            batch_id = str(uuid.uuid4())
            self._conn.execute(
                """INSERT INTO wal_event
                   (seq_no, batch_id, schema_version, event_type, payload_json, payload_hash, status, priority, bytes, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)""",
                (next_seq, batch_id, SCHEMA_VERSION, etype, blob, digest, priority, size, time.time()),
            )
            self._conn.execute("UPDATE wal_meta SET v=? WHERE k='next_seq'", (str(next_seq + 1),))
            self._conn.commit()
            return next_seq

    def pending(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM wal_event WHERE status='pending' ORDER BY seq_no ASC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def ack_through(self, seq_no: int) -> int:
        """Cumulative contiguous ACK: only mark 1..N if every seq ≤ N is present."""
        with self._lock:
            current = int(self._conn.execute("SELECT v FROM wal_meta WHERE k='acked_through'").fetchone()[0])
            if seq_no <= current:
                return current
            missing = self._conn.execute(
                """SELECT seq_no FROM wal_event
                   WHERE seq_no > ? AND seq_no <= ? AND status='pending'
                   ORDER BY seq_no""",
                (current, seq_no),
            ).fetchall()
            expected = list(range(current + 1, seq_no + 1))
            present = [int(r[0]) for r in missing]
            # pending rows that fill the gap
            if present != expected:
                # also allow already-acked in the window
                statuses = self._conn.execute(
                    "SELECT seq_no, status FROM wal_event WHERE seq_no > ? AND seq_no <= ? ORDER BY seq_no",
                    (current, seq_no),
                ).fetchall()
                got = {int(r[0]): r[1] for r in statuses}
                for s in expected:
                    if s not in got:
                        return current
            self._conn.execute(
                "UPDATE wal_event SET status='acked' WHERE seq_no > ? AND seq_no <= ? AND status='pending'",
                (current, seq_no),
            )
            self._conn.execute("UPDATE wal_meta SET v=? WHERE k='acked_through'", (str(seq_no),))
            self._conn.commit()
            return seq_no

    def reject(self, seq_no: int, reason: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE wal_event SET status='rejected' WHERE seq_no=? AND status='pending'",
                (seq_no,),
            )
            self._conn.commit()

    def compact(self) -> int:
        with self._lock:
            cur = self._conn.execute("DELETE FROM wal_event WHERE status='acked'")
            self._conn.commit()
            return cur.rowcount

    def replay_unacked(self) -> Iterable[dict[str, Any]]:
        return self.pending(limit=10_000)
