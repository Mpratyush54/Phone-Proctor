import pytest

from fusion.baselines import assert_no_leakage, evidence_quality, logistic_priority, rules_score
from fusion.ranker import rank


def test_leakage_denylist():
    with pytest.raises(ValueError):
        assert_no_leakage({"gaze_h": 0.1, "fused_score": 0.9, "verdict": "CHEATING"})
    assert_no_leakage({"gaze_h": 0.1, "head_yaw": 2, "face_count": 1})


def test_rules_not_cheating_probability():
    heads = rules_score({"gaze_h": 0.9, "face_count": 2})
    assert "cheat" not in "".join(heads).lower()
    q = evidence_quality({"gaze_h": 0.9, "head_yaw": 1, "face_count": 2})
    prio = logistic_priority(heads, q)
    assert 0 <= prio <= 1


def test_ranker_budget(tmp_path):
    rows = [
        {"gaze_h": 0.0, "face_count": 1},
        {"gaze_h": 0.9, "face_count": 2},
        {"gaze_h": 0.1, "face_count": 0},
    ]
    top = rank(rows, budget=1)
    assert len(top) == 1
    assert top[0] in (1, 2)
