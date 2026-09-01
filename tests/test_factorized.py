import pytest

from tools.factorized_latent import Latent, pair_split_consistent, preserve_pose, validate


def test_rejects_impossible_and_preserves_pose():
    ok = Latent("p", "neutral", "quiet", "laptop", "camera_on", 1.0, 0.0, 0.2, split="train")
    validate(ok)
    bad = Latent("p", "eyes_closed", "quiet", "laptop", "reading_screen", 0, 0, 0)
    with pytest.raises(ValueError):
        validate(bad)
    nxt = Latent("p", "turn", "quiet", "laptop", "camera_on", 99, 99, 9, missingness="camera_drop", split="test")
    held = preserve_pose(ok, nxt)
    assert held.pose_yaw == 1.0
    assert held.split == "train"


def test_counterfactual_pair_same_split():
    a = Latent("pair-1", "neutral", "quiet", "laptop", "camera_on", 0, 0, 0, split="val")
    b = Latent("pair-1", "turn", "quiet", "laptop", "camera_on", 0, 0, 0, split="val")
    assert pair_split_consistent([a, b])
    c = Latent("pair-1", "turn", "quiet", "laptop", "camera_on", 0, 0, 0, split="test")
    assert not pair_split_consistent([a, c])
