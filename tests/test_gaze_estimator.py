"""Tests for gaze/gaze_estimator.py using synthetic MediaPipe-style landmarks."""

import numpy as np

from gaze.gaze_estimator import GazeEstimator


def _landmarks(iris_l=(150.0, 100.0), iris_r=(350.0, 100.0)):
    """Build a 474-length landmark list with two symmetric horizontal eyes.

    Left eye: corners idx33/camera-left (100,100), idx133/camera-right (200,100)
    Right eye: corners idx362/camera-left (300,100), idx263/camera-right (400,100)
    Vertical: top y=80, bottom y=120 for both eyes.
    """
    points = [(0.0, 0.0)] * 474
    # Left eye horizontal
    points[33] = (100.0, 100.0)   # outer
    points[133] = (200.0, 100.0)  # inner
    # Left eye vertical
    points[159] = (150.0, 80.0)
    points[145] = (150.0, 120.0)
    # Right eye horizontal
    points[362] = (300.0, 100.0)  # inner
    points[263] = (400.0, 100.0)  # outer
    # Right eye vertical
    points[386] = (350.0, 80.0)
    points[374] = (350.0, 120.0)
    points[468] = iris_l
    points[473] = iris_r
    return [np.array(p) for p in points]


def test_center_gaze_is_not_away():
    engine = GazeEstimator()
    away, scores = engine.estimate(_landmarks(), (480, 640))
    assert away is False
    assert scores["direction"] == "CENTER"
    assert 0.4 <= scores["h_ratio"] <= 0.6
    assert 0.4 <= scores["v_ratio"] <= 0.6


def test_looking_left_triggers_away():
    engine = GazeEstimator()
    # Iris pushed toward the left (low h_ratio).
    away, scores = engine.estimate(_landmarks(iris_l=(105.0, 100.0), iris_r=(305.0, 100.0)), (480, 640))
    assert away is True
    assert scores["h_ratio"] < 0.42


def test_looking_right_triggers_away():
    engine = GazeEstimator()
    away, scores = engine.estimate(_landmarks(iris_l=(195.0, 100.0), iris_r=(395.0, 100.0)), (480, 640))
    assert away is True
    assert scores["h_ratio"] > 0.58


def test_looking_up_triggers_away():
    engine = GazeEstimator()
    away, scores = engine.estimate(_landmarks(iris_l=(150.0, 86.0), iris_r=(350.0, 86.0)), (480, 640))
    assert away is True
    assert scores["direction"] == "UP"
    assert scores["v_ratio"] < 0.40


def test_looking_down_triggers_away():
    engine = GazeEstimator()
    away, scores = engine.estimate(_landmarks(iris_l=(150.0, 114.0), iris_r=(350.0, 114.0)), (480, 640))
    assert away is True
    assert scores["direction"] == "DOWN"
    assert scores["v_ratio"] > 0.60


def test_degenerate_zero_width_does_not_crash():
    engine = GazeEstimator()
    lms = [(0.0, 0.0)] * 474
    away, scores = engine.estimate([np.array(p) for p in lms], (480, 640))
    assert away is False
    assert scores["h_ratio"] == 0.5
    assert scores["v_ratio"] == 0.5