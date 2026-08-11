"""Tests for fusion/score_fusion.py."""

import pytest

from fusion.score_fusion import ScoreFusion


def test_empty_signals_safe():
    fusion = ScoreFusion()
    result = fusion.fuse({})
    assert result["status"] == "SAFE"
    assert result["score"] == 0.0
    assert result["reasons"] == []
    assert result["contributions"] == []


def test_single_signal_warning():
    fusion = ScoreFusion()
    result = fusion.fuse({"gaze_away": 1, "multi_face": 1})
    assert result["status"] == "WARNING"
    assert result["score"] == pytest.approx(0.35, abs=0.001)
    assert any("Gaze away" in r for r in result["reasons"])


def test_combo_flags():
    fusion = ScoreFusion()
    result = fusion.fuse({"gaze_away": 1, "head_away": 1, "phone_face": 1})
    assert result["status"] == "FLAG"
    assert result["score"] == pytest.approx(0.65, abs=0.001)
    assert len(result["contributions"]) == 3


def test_network_signal_warning():
    fusion = ScoreFusion()
    result = fusion.fuse({"network": 1})
    assert result["status"] == "WARNING"
    assert result["score"] == pytest.approx(0.30, abs=0.001)


def test_values_clamped_to_unit_interval():
    fusion = ScoreFusion()
    result = fusion.fuse({"gaze_away": 5.0})
    assert any(c["value"] == 1.0 for c in result["contributions"])
    assert result["score"] == pytest.approx(0.20, abs=0.001)


def test_partial_weight_contribution():
    fusion = ScoreFusion()
    result = fusion.fuse({"phone_face": 0.5})
    assert result["score"] == pytest.approx(0.125, abs=0.001)
    assert result["contributions"][0]["contribution"] == pytest.approx(0.125, abs=0.001)


def test_verdict_mapping():
    fusion = ScoreFusion()
    assert fusion.verdict("SAFE") == "SAFE"
    assert fusion.verdict("WARNING") == "WARNING"
    assert fusion.verdict("FLAG") == "FLAG"