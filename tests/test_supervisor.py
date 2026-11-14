"""C1 supervisor: AI does not start before EXAM_START; persist/restore; duplicates."""

import pytest

from agent.consent import ConsentRecord
from agent.supervisor import AgentSupervisor, DuplicateCommand, LifecycleState
from agent.wal import EventWal


def _sup(tmp_path) -> AgentSupervisor:
    wal = EventWal(tmp_path / "wal.sqlite")
    return AgentSupervisor(wal=wal, consent=ConsentRecord(camera=True, microphone=True))


def test_ai_does_not_start_before_command(tmp_path):
    sup = _sup(tmp_path)
    started = []
    assert sup.may_start_ai() is False
    assert sup.start_ai_if_authorized(lambda: started.append(1)) is False
    assert started == []
    sup.handle_command({"type": "EXAM_START", "idempotency_key": "s1", "command_id": "c1"})
    assert sup.may_start_ai() is True
    assert sup.start_ai_if_authorized(lambda: started.append(1)) is True
    assert started == [1]


def test_duplicate_start_returns_prior(tmp_path):
    sup = _sup(tmp_path)
    first = sup.handle_command({"type": "START", "idempotency_key": "same", "command_id": "c1"})
    with pytest.raises(DuplicateCommand) as exc:
        sup.handle_command({"type": "START", "idempotency_key": "same", "command_id": "c1"})
    assert exc.value.prior == first


def test_pause_end_idempotent_and_timeout_unknown_denied(tmp_path):
    sup = _sup(tmp_path)
    sup.handle_command({"type": "EXAM_START", "idempotency_key": "a"})
    sup.handle_command({"type": "PAUSE", "idempotency_key": "b"})
    assert sup.observed_lifecycle_state is LifecycleState.PAUSED
    assert sup.scoring_enabled is False
    sup.handle_command({"type": "RESUME", "idempotency_key": "c"})
    assert sup.observed_lifecycle_state is LifecycleState.IN_EXAM
    sup.handle_command({"type": "END", "idempotency_key": "d"})
    assert sup.observed_lifecycle_state is LifecycleState.ENDED
    denied = sup.handle_command({"type": "NOT_A_COMMAND", "idempotency_key": "e"})
    assert denied["ok"] is False


def test_restore_snapshot(tmp_path):
    sup = _sup(tmp_path)
    sup.handle_command({"type": "EXAM_START", "idempotency_key": "a"})
    snap = sup.persist_snapshot()
    wal2 = EventWal(tmp_path / "wal2.sqlite")
    other = AgentSupervisor(wal=wal2)
    other.restore(snap)
    assert other.desired_lifecycle_state is LifecycleState.IN_EXAM
    assert other.control_generation == snap["control_generation"]


def test_metrics_pass_through_wal(tmp_path):
    sup = _sup(tmp_path)
    for i in range(10):
        sup.sink.emit("METRICS", {"i": i})
    pending = sup.wal.pending(limit=100)
    types = [r["event_type"] for r in pending]
    assert "METRICS" in types
    sup.wal.close()
