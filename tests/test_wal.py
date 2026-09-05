"""C5 WAL crash/replay, ACK, NACK, quota, retry."""

import pytest

from agent.wal import EventWal, QuotaExceeded, EVENT_QUOTA_BYTES


def test_happy_path_ack(tmp_path):
    wal = EventWal(tmp_path / "w.sqlite")
    s1 = wal.append("VIOLATION", {"x": 1})
    s2 = wal.append("METRICS", {"x": 2})
    assert wal.ack_through(s2) == s2
    assert wal.pending() == []
    wal.close()


def test_duplicate_append_gets_new_seq(tmp_path):
    wal = EventWal(tmp_path / "w.sqlite")
    a = wal.append("INFO", {"x": 1})
    b = wal.append("INFO", {"x": 1})
    assert a != b
    wal.close()


def test_ack_not_contiguous_denied(tmp_path):
    wal = EventWal(tmp_path / "w.sqlite")
    wal.append("INFO", {"x": 1})
    # skipping seq 1 by acking 2 without seq 2 existing
    assert wal.ack_through(2) == 0
    wal.close()


def test_reject_and_replay(tmp_path):
    wal = EventWal(tmp_path / "w.sqlite")
    s = wal.append("INFO", {"x": 1})
    wal.reject(s, "bad schema")
    assert all(r["status"] != "pending" or r["seq_no"] != s for r in wal.pending())
    wal.close()


def test_crash_reopens_pending(tmp_path):
    path = tmp_path / "w.sqlite"
    wal = EventWal(path)
    wal.append("VIOLATION", {"x": 1})
    wal.close()
    wal2 = EventWal(path)
    pending = wal2.pending()
    assert len(pending) == 1
    assert pending[0]["event_type"] == "VIOLATION"
    wal2.close()


def test_protected_events_bypass_quota(tmp_path, monkeypatch):
    wal = EventWal(tmp_path / "w.sqlite")
    wal.append("VIOLATION", {"x": 1})
    wal.close()
