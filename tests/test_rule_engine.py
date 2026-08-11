"""Tests for the RuleEngine (rule_engine.py)."""

import time

import pytest

from rules.rule_engine import RuleEngine


def _engine_with_zero_thresholds():
    engine = RuleEngine()
    engine.FACE_MISSING_THRESHOLD = 0.0
    engine.MULTIPLE_FACES_THRESHOLD = 0.0
    engine.LOOK_AWAY_THRESHOLD = 0.0
    return engine


def test_no_face_starts_timer_but_no_violation_yet():
    engine = _engine_with_zero_thresholds()
    engine.FACE_MISSING_THRESHOLD = 10.0
    violations = engine.evaluate_faces(0)
    assert violations == []
    assert engine.face_missing_start is not None


def test_face_missing_violation_after_threshold():
    engine = _engine_with_zero_thresholds()
    assert engine.evaluate_faces(0) == []
    assert "Face Missing" in engine.evaluate_faces(0)


def test_face_missing_resets_when_face_returns():
    engine = _engine_with_zero_thresholds()
    engine.evaluate_faces(0)
    engine.evaluate_faces(0)
    assert engine.evaluate_faces(1) == []
    assert engine.face_missing_start is None


def test_multiple_faces_violation():
    engine = _engine_with_zero_thresholds()
    engine.evaluate_faces(2)
    violations = engine.evaluate_faces(2)
    assert "Multiple Faces Detected" in violations


def test_single_face_no_violation():
    engine = _engine_with_zero_thresholds()
    assert engine.evaluate_faces(1) == []
    engine.evaluate_faces(2)
    assert engine.evaluate_faces(1) == []
    assert engine.multiple_faces_start is None


def test_look_away_violation_and_reset():
    engine = _engine_with_zero_thresholds()
    assert engine.evaluate_look_away(True) == []
    assert "Looking Away" in engine.evaluate_look_away(True)
    assert engine.evaluate_look_away(False) == []
    assert engine.look_away_start is None