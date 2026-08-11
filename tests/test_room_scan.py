"""Tests for analysis/room_scan.py (dependency-injected, OpenCV available)."""

import numpy as np
import pytest

from analysis.room_scan import RoomScanner
from rules.thresholds import Thresholds


def _thresholds(**room_overrides):
    config = Thresholds().config
    cfg = {**config}
    cfg["room_scan"] = {**config["room_scan"], "scan_enabled": True, "base_frames": 3, **room_overrides}
    return Thresholds(cfg)


def _frame(value):
    return np.full((64, 64, 3), value, dtype=np.uint8)


def test_build_baseline_requires_frames():
    scanner = RoomScanner(_thresholds())
    ok, notes = scanner.build_baseline()
    assert ok is False
    assert scanner.has_baseline is False


def test_baseline_build_and_scanning(tmp_path):
    scanner = RoomScanner(_thresholds())
    for _ in range(3):
        scanner.feed_baseline_frame(_frame(10))
    ok, notes = scanner.build_baseline()
    assert ok is True
    assert scanner.has_baseline is True

    # Identical frame -> no scene change.
    result = scanner.scan_frame(_frame(10), cooldown_sec=0)
    assert result["changed"] is False
    assert result["faces"] == 0

    # Dramatically different frame -> change detected.
    result = scanner.scan_frame(_frame(200), cooldown_sec=0)
    assert result["changed"] is True
    assert any("scene change" in n for n in result["notes"])


def test_scan_respects_cooldown():
    scanner = RoomScanner(_thresholds())
    for _ in range(3):
        scanner.feed_baseline_frame(_frame(10))
    scanner.build_baseline()
    # First scan runs unconditionally (last_scan_time starts at 0).
    scanner.scan_frame(_frame(10), cooldown_sec=0)
    # Immediately after, a 60s cooldown should return the cached result.
    result = scanner.scan_frame(_frame(200), cooldown_sec=60)
    assert result["changed"] is False


def test_second_person_persistence():
    class FakeFaceDetector:
        def __init__(self, faces):
            self.faces = faces

        def detect(self, frame):
            return self.faces

    detector = FakeFaceDetector([(0, 0, 10, 10), (20, 0, 10, 10)])  # 2 faces
    scanner = RoomScanner(_thresholds(min_second_person_frames=3), face_detector=detector)
    for _ in range(3):
        scanner.feed_baseline_frame(_frame(10))
    scanner.build_baseline()

    result = {}
    for _ in range(3):
        result = scanner.scan_frame(_frame(10), cooldown_sec=0)
    assert result["changed"] is True
    assert any("Second person" in n for n in result["notes"])
    assert result["faces"] == 2


def test_new_restricted_object_detected():
    class FakeObjectDetector:
        """Returns nothing during baseline, then a phone mid-exam."""

        def __init__(self):
            self.frames_seen = 0

        def detect(self, frame):
            self.frames_seen += 1
            if self.frames_seen <= 3:
                return [], (0, 0)  # baseline: clean room
            return ["Cell Phone Detected"], (1, 1)

    scanner = RoomScanner(_thresholds(), object_detector=FakeObjectDetector())
    for _ in range(3):
        scanner.feed_baseline_frame(_frame(10))
    scanner.build_baseline()
    # Baseline had no phone; now a phone appears mid-exam.
    result = scanner.scan_frame(_frame(10), cooldown_sec=0)
    assert result["changed"] is True
    assert any("New object in room" in n for n in result["notes"])


def test_restricted_object_in_baseline_not_flagged():
    class FakeObjectDetector:
        def detect(self, frame):
            return ["Book/Notes Detected"], (1, 1)

    scanner = RoomScanner(_thresholds(), object_detector=FakeObjectDetector())
    for _ in range(3):
        scanner.feed_baseline_frame(_frame(10))
    scanner.build_baseline()  # book already present at start

    result = scanner.scan_frame(_frame(10), cooldown_sec=0)
    assert result["changed"] is False


def test_frame_brightness():
    scanner = RoomScanner(_thresholds())
    assert scanner._frame_brightness(_frame(0)) == pytest.approx(0.0)
    assert scanner._frame_brightness(_frame(255)) == pytest.approx(1.0)


def test_scan_disabled_returns_passive():
    scanner = RoomScanner(_thresholds(scan_enabled=False))
    scanner.feed_baseline_frame(_frame(10))
    ok, _ = scanner.build_baseline()
    assert ok is False
    assert scanner.scan_frame(_frame(10)) == scanner.last_scan