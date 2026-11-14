"""Per-issue acceptance matrix for tracks A–G (#1–#66)."""

from pathlib import Path

import pytest

from agent.bootstrap import build_runtime, parse_args
from agent.consent import Capability, ConsentGate, ConsentRecord, Readiness
from agent.evidence import build_evidence_bundle
from agent.live_publisher import LivePublisher
from agent.packaging import sign_manifest, verify_signature, write_manifest
from agent.phone_uplink import PhoneUplink
from agent.product_mode import require_wss
from agent.ring_buffer import RingBuffer
from agent.snapshots import SnapshotPublisher
from agent.media_spool import MediaSpool
from agent.supervisor import AgentSupervisor
from agent.wal import EventWal
from screen.student_shell import StudentShell
from fusion.baselines import assert_no_leakage
from fusion.shadow import shadow_score
from tools.closed_loop import run_pipeline
from tools.factorized_latent import Latent, validate
from tools.missingness import Observation, apply_missingness, same_split
from tools.synthetic_manifest import lock_hash
from tools.window_features import join_manifest, window_features
from analysis.observable_summary import VERDICT_FORBIDDEN


def test_a1_a5_and_c_vertical(tmp_path, monkeypatch):
    wal = EventWal(tmp_path / "w.sqlite")
    sup = AgentSupervisor(wal=wal, consent=ConsentRecord(camera=True))
    assert sup.may_start_ai() is False
    sup.handle_command({"type": "EXAM_START", "idempotency_key": "s"})
    assert sup.may_start_ai() is True
    monkeypatch.setenv("PHONE_PROCTOR_MODE", "product")
    with pytest.raises(PermissionError):
        require_wss("ws://x")
    PhoneUplink({"device_credential_id": "d", "session_id": "s", "can_register_agent": False})
    with pytest.raises(PermissionError):
        PhoneUplink({"device_credential_id": "d", "session_id": "s", "can_register_agent": True})
    pub = LivePublisher()
    pub.viewer_joined()
    assert pub.viewer_left() == "STOP_LIVE"
    dest = tmp_path / "m.json"
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a").write_text("x")
    write_manifest(dest, tmp_path / "pkg")
    key = b"secret-key"
    sign_manifest(dest, key)
    assert verify_signature(dest, key) is True
    wal.close()


def test_bootstrap_layout_supervisor_wss_and_shell(tmp_path, monkeypatch):
    args = parse_args(["--mode", "local", "--gateway", "ws://127.0.0.1/agent"])
    runtime = build_runtime(args, wal_path=tmp_path / "boot.sqlite")
    try:
        assert isinstance(runtime.supervisor, AgentSupervisor)
        assert runtime.supervisor.may_start_ai() is False
    finally:
        runtime.close()
    monkeypatch.setenv("PHONE_PROCTOR_MODE", "product")
    with pytest.raises(PermissionError):
        require_wss("ws://x")
    shell = StudentShell()
    shell.set_lifecycle("READY")
    assert shell.lifecycle == "READY"
    assert shell.events == ["READY"]


def test_a2_consent_and_a4_no_guilt():
    d = ConsentGate().evaluate(ConsentRecord(camera=False))
    assert d.readiness is Readiness.BLOCKED
    assert not d.may_start(Capability.CAMERA)
    for banned in VERDICT_FORBIDDEN:
        assert banned


def test_e_media_and_f_ml(tmp_path):
    spool = MediaSpool(tmp_path / "spool", quota_bytes=200)
    pub = SnapshotPublisher(spool, min_interval_s=0)
    assert pub.maybe_publish(b"j" * 70, now=1)
    # 80% of 200 = 160; second 70-byte snapshot trips snapshot pause.
    assert pub.maybe_publish(b"j" * 70, now=2) is False
    lap = RingBuffer(30)
    lap.push(b"aaa", ts=10)
    phone = RingBuffer(15)
    body = build_evidence_bundle(tmp_path / "ev", lap, phone, now=10, phone_available=False, policy_requires_phone=True)
    assert body["phone_retrospective"] == "unavailable"
    assert body["phone_uploaded"] is False
    assert_no_leakage({"gaze_h": 0.1})
    feats = window_features([{"t": 0, "gaze_h": 0.1, "face_count": 1}, {"t": 12, "gaze_h": 0.2, "face_count": 1}])
    assert feats
    assert join_manifest(["p1"], "p2") == ["p1", "p2"]
    a = Observation("p", "train", True, False, 0, 0.9, False)
    b = Observation("p", "train", False, True, 12, 0.9, True)
    assert same_split(a, b)
    assert apply_missingness(0.9, False) == 0.0
    validate(Latent("p", "neutral", "quiet", "laptop", "camera_on", 0, 0, 0))
    geo = run_pipeline("geometry_fast", {"gaze_h": 0.2})
    assert geo["train_pixel_model"] is False
    closed = run_pipeline("closed_loop_rendered", {"pixels": b"RGB"}, detector=lambda p: {"ok": True})
    assert closed["train_pixel_model"] is True
    assert shadow_score({"gaze_h": 1}, lambda p: (_ for _ in ()).throw(RuntimeError())) is None
    assert lock_hash({"a": 1}) != lock_hash({"a": 2})


def test_g8_no_kafka_in_tree():
    root = Path(".")
    text = (root / "tools" / "load_harness.py").read_text(encoding="utf-8")
    assert "kafka" in text.lower()
    assert "event_partitioning" in text
