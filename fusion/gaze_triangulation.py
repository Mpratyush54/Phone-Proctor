"""
3D Gaze Triangulation (VISION.md Section 6, Design Doc Section 12.2)

Combines the frontal webcam head-pose (yaw/pitch) with the phone-side camera
observation to estimate *where* the candidate is looking in 3D space.

Geometry (right-handed, units = cm):
  - Webcam sits at origin (0, 0, 0), looking down +Z toward the screen.
  - Screen plane at z = screen_distance_cm, centered at (0, 0, screen_distance_cm).
  - Phone camera offset on the +X axis: phone_offset_x_cm, z = phone_offset_z_cm.

A gaze ray is cast from the webcam along the head-pose direction and intersected
with the screen plane. The phone "face detected" signal tells us the head is
turned toward the phone, which strongly implies the candidate is looking at the
phone (or away from the screen) rather than at the screen.

The module is pure NumPy/math so it is deterministically unit-testable without
any camera hardware.
"""

import math

import numpy as np


class GazeTriangulator:
    def __init__(self, thresholds=None):
        if thresholds is None:
            from rules.thresholds import Thresholds
            thresholds = Thresholds()

        self.screen_distance_cm = thresholds.triangulation("screen_distance_cm", default=60.0)
        self.screen_half_width_cm = thresholds.triangulation("screen_half_width_cm", default=40.0)
        self.screen_half_height_cm = thresholds.triangulation("screen_half_height_cm", default=25.0)
        self.phone_offset_x_cm = thresholds.triangulation("phone_offset_x_cm", default=45.0)
        self.phone_offset_z_cm = thresholds.triangulation("phone_offset_z_cm", default=30.0)
        self.gaze_cone_deg = thresholds.triangulation("gaze_cone_deg", default=5.0)

    #
    # Pure math helpers (exposed for testing)
    #
    def gaze_vector(self, yaw_deg, pitch_deg):
        """
        Converts yaw/pitch angles (degrees) into a unit gaze direction vector.
        yaw>0 = turning right, pitch>0 = looking up (camera convention).
        """
        yaw = math.radians(yaw_deg)
        pitch = math.radians(pitch_deg)
        x = math.sin(yaw) * math.cos(pitch)
        y = math.sin(pitch) * math.cos(yaw)
        z = math.cos(yaw) * math.cos(pitch)
        v = np.array([x, y, z], dtype=float)
        norm = np.linalg.norm(v)
        return v / norm if norm > 0 else np.array([0.0, 0.0, 1.0])

    def ray_z_value(self, z):
        """Amount of the gaze vector that points into the screen plane."""
        return z

    def intersect_screen(self, yaw_deg, pitch_deg):
        """
        Casts the gaze ray from the webcam origin and intersects it with the
        screen plane at z = screen_distance_cm.
        Returns (point3d, on_screen: bool)
        point3d is None if the ray never reaches the screen plane.
        """
        direction = self.gaze_vector(yaw_deg, pitch_deg)
        z = direction[2]
        if z <= 1e-9:
            return None, False

        t = self.screen_distance_cm / z
        point = direction * t
        on_screen = (
            abs(point[0]) <= self.screen_half_width_cm
            and abs(point[1]) <= self.screen_half_height_cm
        )
        return point, on_screen

    def phone_vector(self):
        """Unit vector from the phone camera location toward the candidate region."""
        # Phone looks back toward the origin (the candidate's head area).
        delta = np.array([-self.phone_offset_x_cm, 0.0, -self.phone_offset_z_cm], dtype=float)
        norm = np.linalg.norm(delta)
        return delta / norm if norm > 0 else np.array([-1.0, 0.0, 0.0])

    def phone_line_position(self):
        """3D position of the phone camera."""
        return np.array([self.phone_offset_x_cm, 0.0, self.phone_offset_z_cm], dtype=float)

    def ray_to_point_distance(self, origin, direction, point):
        """Perpendicular distance from a 3D point to a ray."""
        origin = np.asarray(origin, dtype=float)
        direction = np.asarray(direction, dtype=float)
        point = np.asarray(point, dtype=float)
        w = point - origin
        t = np.dot(w, direction) / (np.dot(direction, direction) + 1e-12)
        t = max(t, 0.0)
        closest = origin + t * direction
        return float(np.linalg.norm(point - closest))

    #
    # Main entry point
    #
    def triangulate(self, yaw_deg, pitch_deg, phone_face_detected=False, phone_looking=True):
        """
        Combines webcam head pose with the phone observation.

        Returns a dict:
          {
            "gaze_point": (x, y, z) or None,   # 3D intersection with screen plane
            "on_screen": bool,
            "screen_region": "CENTER"|"LEFT"|"RIGHT"|"TOP"|"BOTTOM"|"OFF_SCREEN",
            "phone_face_detected": bool,
            "phone_distance_cm": float,          # dist from gaze hit to phone
            "looking_at_phone": bool,            # fused decision
            "looking_away": bool                 # not at the screen center
          }
        """
        point, on_screen = self.intersect_screen(yaw_deg, pitch_deg)

        phone_pos = self.phone_line_position()
        screen_center = np.array([0.0, 0.0, self.screen_distance_cm])

        # Distance from the gaze hit-point to the phone (if we have a hit).
        phone_distance_cm = float("inf")
        if point is not None:
            phone_distance_cm = self.ray_to_point_distance(
                np.zeros(3), self.gaze_vector(yaw_deg, pitch_deg), phone_pos
            )

        # Screen region classification (only meaningful when on_screen)
        region = "OFF_SCREEN"
        if point is not None:
            if not on_screen:
                region = "OFF_SCREEN"
            else:
                x, y = point[0], point[1]
                if x > self.screen_half_width_cm * 0.4:
                    region = "RIGHT"
                elif x < -self.screen_half_width_cm * 0.4:
                    region = "LEFT"
                elif y > self.screen_half_height_cm * 0.4:
                    region = "TOP"
                elif y < -self.screen_half_height_cm * 0.4:
                    region = "BOTTOM"
                else:
                    region = "CENTER"

        # Fused decision:
        #  - Phone face visible + head turned => candidate is looking at phone area.
        #  - Gaze hit near the phone => looking toward phone / hand.
        looking_at_phone = False
        if point is not None:
            if phone_face_detected or phone_distance_cm < self.phone_offset_x_cm * 0.8:
                looking_at_phone = True

        # looking_away = not centered on the screen
        looking_away = region != "CENTER"
        if phone_face_detected:
            looking_away = True

        return {
            "gaze_point": tuple(point) if point is not None else None,
            "on_screen": bool(on_screen),
            "screen_region": region,
            "phone_face_detected": bool(phone_face_detected),
            "phone_distance_cm": round(phone_distance_cm, 2),
            "looking_at_phone": bool(looking_at_phone),
            "looking_away": bool(looking_away),
        }