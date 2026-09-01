import pytest

from agent.media_spool import MediaSpool
from agent.ring_buffer import RingBuffer


def test_snapshots_pause_under_backpressure(tmp_path):
    spool = MediaSpool(root=tmp_path, quota_bytes=100)
    spool.enqueue("evidence", b"x" * 90, {"id": "e"})
    with pytest.raises(RuntimeError):
        spool.enqueue("snapshot", b"y" * 20, {"id": "s"})
    assert spool.snapshots_paused


def test_retry_then_dead_letter(tmp_path):
    spool = MediaSpool(root=tmp_path)
    p = spool.enqueue("snapshot", b"jpeg", {"id": "s"})
    meta = p.with_suffix(".json")
    rec = None
    for _ in range(10):
        rec = spool.mark_attempt(meta, ok=False)
    assert rec and rec.get("dead_letter") is True


def test_ring_buffer_hashes(tmp_path):
    buf = RingBuffer(1.0, "laptop")
    buf.push(b"aaa", ts=1.0)
    buf.push(b"bbb", ts=1.5)
    frames = buf.snapshot(pre_s=1, post_s=0, now=1.5)
    assert len(frames) == 2
    assert len(buf.hashes(frames)[0]) == 64
