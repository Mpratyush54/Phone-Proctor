import cv2
import numpy as np


class HeadPoseEstimator:
    def __init__(self):
        # 3D model points (approximate)
        # Image coordinates: +x = image right, +y = image down (matches the raw
        # MediaPipe landmark output and OpenCV's pinhole convention).
        self.model_points = np.array([
            (0.0, 0.0, 0.0),        # Nose tip
            (0.0, 63.6, -12.5),    # Chin (below nose in image)
            (-43.3, -32.7, -26.0),  # Left eye corner
            (43.3, -32.7, -26.0),   # Right eye corner
            (-28.9, 28.9, -24.1),   # Left mouth corner
            (28.9, 28.9, -24.1)     # Right mouth corner
        ], dtype="double")

        # MediaPipe landmark indices
        self.landmark_ids = [1, 152, 33, 263, 61, 291]

    def estimate(self, landmarks, frame_shape):
        image_points = np.array(
            [landmarks[i] for i in self.landmark_ids],
            dtype="double"
        )

        h, w = frame_shape[:2]
        focal_length = w
        center = (w / 2, h / 2)

        camera_matrix = np.array([
            [focal_length, 0, center[0]],
            [0, focal_length, center[1]],
            [0, 0, 1]
        ], dtype="double")

        dist_coeffs = np.zeros((4, 1))

        success, rotation_vec, _ = cv2.solvePnP(
            self.model_points,
            image_points,
            camera_matrix,
            dist_coeffs,
            flags=cv2.SOLVEPNP_ITERATIVE
        )

        if not success:
            return None, None

        rmat, _ = cv2.Rodrigues(rotation_vec)
        angles, _, _, _, _, _ = cv2.RQDecomp3x3(rmat)

        # IMPORTANT: angles are already in degrees. The model uses +y = image
        # down (matches MediaPipe output), so the recovered rotation about X
        # has opposite sign to the head-local "nose up" convention used by the
        # simulator/runtime (positive pitch = nose up).
        pitch = -angles[0]
        yaw = angles[1]

        return yaw, pitch
