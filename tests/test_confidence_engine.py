"""Tests for ai/confidence_engine.py."""

from ai.confidence_engine import ConfidenceEngine


def test_safe_baseline():
    engine = ConfidenceEngine()
    result = engine.evaluate(vad_prob=0.1, lip_prob=0.1, head_yaw=5, head_pitch=5, face_count=1)
    assert result["status"] == "SAFE"
    assert result["score"] == 0.0
    assert result["reasons"] == []


def test_external_voice_flags():
    engine = ConfidenceEngine()
    result = engine.evaluate(vad_prob=0.9, lip_prob=0.1, head_yaw=0, head_pitch=0, face_count=1)
    assert result["status"] == "FLAG"
    assert result["score"] == 0.8
    assert result["metadata"]["is_external_audio"] is True
    assert any("External Voice" in r for r in result["reasons"])


def test_user_speaking_is_warning():
    engine = ConfidenceEngine()
    result = engine.evaluate(vad_prob=0.9, lip_prob=0.9, head_yaw=0, head_pitch=0, face_count=1)
    assert result["status"] == "WARNING"
    assert result["metadata"]["is_speaking"] is True


def test_multiple_faces_instant_flag():
    engine = ConfidenceEngine()
    result = engine.evaluate(vad_prob=0.0, lip_prob=0.0, head_yaw=0, head_pitch=0, face_count=2)
    assert result["status"] == "FLAG"
    assert result["score"] == 1.0
    assert any("Multiple Faces" in r for r in result["reasons"])


def test_no_face_warning():
    engine = ConfidenceEngine()
    result = engine.evaluate(vad_prob=0.0, lip_prob=0.0, head_yaw=0, head_pitch=0, face_count=0)
    assert result["status"] == "WARNING"
    assert result["score"] == 0.5


def test_head_pose_contributions():
    engine = ConfidenceEngine()
    result = engine.evaluate(vad_prob=0.0, lip_prob=0.0, head_yaw=40, head_pitch=30, face_count=1)
    assert result["score"] == 0.5  # 0.3 yaw + 0.2 pitch
    assert result["status"] == "WARNING"
    assert any("Looking Away" in r for r in result["reasons"])
    assert any("Looking Up/Down" in r for r in result["reasons"])


def test_score_capped_at_one():
    engine = ConfidenceEngine()
    result = engine.evaluate(vad_prob=0.9, lip_prob=0.1, head_yaw=40, head_pitch=30, face_count=2)
    assert result["score"] == 1.0