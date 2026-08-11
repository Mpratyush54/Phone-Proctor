"""
Renderer abstraction (tools/renderers/base.py)

Defines the pose -> RGB frame contract shared by every renderer backend
(analytic, Blender/bpy, Omniverse). A renderer must produce a synthetic
webcam frame whose camera intrinsics match gaze/head_pose.py:

    focal_px == image width, principal point == (w/2, h/2)

so that MediaPipe landmarks extracted from the frame feed solvePnP with the
same camera model the runtime uses.

Coordinate convention (world, right-handed, mm):
    webcam at origin, optical axis +Z toward the candidate.
    head-local: +x = subject's right, +y = up, +z = back of head.
"""

import abc


class Camera:
    """Pinhole camera matching gaze/head_pose.py intrinsics."""

    def __init__(self, width=640, height=480):
        self.width, self.height = width, height
        self.focal = float(width)
        self.cx, self.cy = width / 2.0, height / 2.0

    def project(self, points3):
        """Nx3 world (mm) -> Nx2 image pixels (y-down, like real webcams)."""
        import numpy as np

        x, y, z = points3[:, 0], points3[:, 1], points3[:, 2]
        with np.errstate(divide="ignore", invalid="ignore"):
            u = self.cx + self.focal * x / z
            v = self.cy - self.focal * y / z
        return np.stack([u, v], axis=-1)


class BaseRenderer(abc.ABC):
    """Contract: one 8-bit BGR webcam frame for one head pose."""

    def __init__(self, width=640, height=480, seed=0):
        self.width, self.height = width, height
        self.seed = int(seed)
        self.cam = Camera(width, height)

    @abc.abstractmethod
    def render(self, yaw_deg, pitch_deg, roll_deg, head_center, gaze=None):
        """
        Render one frame.

        yaw_deg / pitch_deg / roll_deg : head rotation (head-local).
        head_center                    : (3,) world mm position of nose tip.
        gaze                           : optional dict with iris placements.
        Returns 8-bit BGR numpy array (height, width, 3).
        """
