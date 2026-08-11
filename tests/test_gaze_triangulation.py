"""Tests for fusion/gaze_triangulation.py (pure 3D math, no hardware)."""

import math

import numpy as np
import pytest

from fusion.gaze_triangulation import GazeTriangulator
from rules.thresholds import Thresholds


def _triangulator(**overrides):
    config = Thresholds().config
    cfg = {**config}
    cfg["triangulation"] = {**config["triangulation"], **overrides}
    return GazeTriangulator(Thresholds(cfg))


def test_gaze_vector_unit_length():
    t = _triangulator()
    v = t.gaze_vector(25, 10)
    assert abs(np.linalg.norm(v) - 1.0) < 1e-9


def test_forward_gaze_hits_screen_center():
    t = _triangulator()
    point, on_screen = t.intersect_screen(0, 0)
    assert bool(on_screen) is True
    assert point is not None
    assert point[2] == pytest.approx(t.screen_distance_cm)
    assert abs(point[0]) < 1e-6
    assert abs(point[1]) < 1e-6


def test_extreme_yaw_off_screen():
    t = _triangulator()
    point, on_screen = t.intersect_screen(70, 0)
    assert bool(on_screen) is False
    assert point is None or abs(point[0]) > t.screen_half_width_cm


def test_gaze_backwards_returns_none():
    t = _triangulator()
    point, on_screen = t.intersect_screen(180, 0)
    assert point is None
    assert on_screen is False


def test_triangulate_center_looking_at_screen():
    t = _triangulator()
    result = t.triangulate(0, 0)
    assert result["on_screen"] is True
    assert result["screen_region"] == "CENTER"
    assert result["looking_away"] is False
    assert result["looking_at_phone"] is False


def test_triangulate_phone_face_looking_away():
    t = _triangulator()
    result = t.triangulate(0, 0, phone_face_detected=True)
    assert result["looking_at_phone"] is True
    assert result["looking_away"] is True
    assert result["phone_face_detected"] is True


def test_region_classification():
    t = _triangulator()
    # Moderate right yaw => gaze lands on right half of the screen.
    result = t.triangulate(20, 0)
    assert result["on_screen"] is True
    assert result["screen_region"] == "RIGHT"
    # Moderate up pitch => top region.
    result = t.triangulate(0, 15)
    assert result["on_screen"] is True
    assert result["screen_region"] == "TOP"


def test_ray_to_point_distance():
    t = _triangulator()
    # Ray along +Z from origin; phone sits offset on +X. Distance should be >0.
    d = t.ray_to_point_distance([0, 0, 0], [0, 0, 1], [t.phone_offset_x_cm, 0, t.phone_offset_z_cm])
    assert d == pytest.approx(t.phone_offset_x_cm)
    # Point exactly on the ray line -> distance zero.
    d2 = t.ray_to_point_distance([0, 0, 0], [0, 0, 1], [0, 0, 5])
    assert d2 == pytest.approx(0.0, abs=1e-9)