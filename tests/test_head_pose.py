"""Tests for gaze/head_pose.py (solvePnP round-trip on synthetic landmarks)."""

import numpy as np

from gaze.head_pose import HeadPoseEstimator


def _project(model, fx, cx, cy, tz):
    """Project model points with the camera model used by HeadPoseEstimator."""
    pts = []
    for x, y, z in model:
        zz = z + tz  # place the head in front of the camera
        pts.append((cx + fx * x / zz, cy + fx * y / zz))
    return pts


def _frontal_landmarks():
    """Landmarks that exactly match an identity-pose projection of the 3D model."""
    estimator = HeadPoseEstimator()
    fx = 640.0
    cx, cy = 320.0, 240.0
    tz = 600.0

    ids = estimator.landmark_ids
    pts = _project(estimator.model_points, fx, cx, cy, tz)
    points = [(0.0, 0.0)] * 468
    for idx, p in zip(ids, pts):
        points[idx] = (p[0], p[1])
    return [np.array(p, dtype=float) for p in points]


def test_frontal_face_roundtrip_near_zero_pose():
    estimator = HeadPoseEstimator()
    yaw, pitch = estimator.estimate(_frontal_landmarks(), (480, 640))
    assert yaw is not None and pitch is not None
    assert abs(yaw) < 3.0
    assert abs(pitch) < 3.0


def test_returns_floats():
    estimator = HeadPoseEstimator()
    yaw, pitch = estimator.estimate(_frontal_landmarks(), (480, 640))
    assert isinstance(yaw, (int, float))
    assert isinstance(pitch, (int, float))


def test_yaw_rotation_is_measurable():
    estimator = HeadPoseEstimator()
    # Rotate the model yaw by +30 degrees and re-project; estimator should
    # recover a yaw significantly different from zero.
    cos, sin = np.cos(np.radians(30)), np.sin(np.radians(30))
    rot = np.array([[cos, 0, sin], [0, 1, 0], [-sin, 0, cos]])
    model = estimator.model_points
    yaw_front, _ = estimator.estimate(_frontal_landmarks(), (480, 640))
    pts = _project(model @ rot.T, 640.0, 320.0, 240.0, 600.0)
    points = [(0.0, 0.0)] * 468
    for idx, p in zip(estimator.landmark_ids, pts):
        points[idx] = (p[0], p[1])
    lms = [np.array(p, dtype=float) for p in points]
    yaw_turned, _ = estimator.estimate(lms, (480, 640))
    assert abs(yaw_turned - yaw_front) > 10.0