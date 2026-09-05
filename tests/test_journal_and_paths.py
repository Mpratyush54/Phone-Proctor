"""Unit tests for write-ahead journal (no Qt / torch required)."""
from __future__ import annotations

import json
from pathlib import Path

from agent.journal import WriteAheadJournal


def test_journal_append_ack_replay(tmp_path: Path):
    j = WriteAheadJournal("sess1", base_dir=tmp_path)
    b1 = j.append("VIOLATION", {"msg": "look away"})
    b2 = j.append("METRICS", {"score": 0.4})
    assert b1.seq_no == 1
    assert b2.seq_no == 2

    pending = j.iter_unacked()
    assert len(pending) == 2
    assert pending[0].batch_id == b1.batch_id

    n = j.ack([b1.batch_id])
    assert n == 1
    pending = j.iter_unacked()
    assert len(pending) == 1
    assert pending[0].batch_id == b2.batch_id

    j.compact_acked()
    lines = (tmp_path / "wal.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["batch_id"] == b2.batch_id


def test_paths_helpers():
    from utils.paths import app_root, resource_path, writable_data_dir

    root = app_root()
    assert root.exists()
    assert resource_path("config").name == "config"
    d = writable_data_dir("test_journal_probe")
    assert d.exists()
