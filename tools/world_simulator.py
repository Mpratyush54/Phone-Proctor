"""
World Simulator for synthetic proctoring data (tools/world_simulator.py)

Instead of sampling yaw/pitch/gaze numbers from a distribution, this module
simulates a 3D scene (webcam + screen + phone side-camera + candidate head)
and produces per-frame measurements by pushing the scene through the SAME
production math the runtime uses:

    - gaze/head_pose.HeadPoseEstimator   (solvePnP yaw/pitch from projected landmarks)
    - gaze/gaze_estimator.GazeEstimator  (iris-ratio gaze from projected eyes)
    - fusion/gaze_triangulation.GazeTriangulator (screen-plane ray casting, 2-camera fusion)
    - fusion/score_fusion.ScoreFusion    (multi-modal fused score/status)
    - the runtime's per-session calibration baseline + EMA smoothing (alpha=0.15)
      and its thresholds (+/-35 deg yaw, +/-30 deg pitch)

This makes synthetic measurements carry the same camera-dependent and
calibration-dependent artifacts as real ones.

Coordinate convention (right-handed, units: mm for the head model, cm for scene):
    world: webcam at origin (0,0,0), optical axis +Z (toward the candidate).
           screen at z = screen_distance_cm. phone camera at (phone_offset_x, 0, phone_offset_z).
    head-local: +x = subject's right, +y = up, +z = toward the back of the head.
"""

import math

import cv2
import numpy as np

from rules.thresholds import Thresholds
from gaze.head_pose import HeadPoseEstimator
from gaze.gaze_estimator import GazeEstimator
from fusion.gaze_triangulation import GazeTriangulator
from fusion.score_fusion import ScoreFusion


# ---------------------------------------------------------------------------
# Head-local 3D model (mm). Mirrors the 6-point model in gaze/head_pose.py and
# adds the eye corners / iris points needed by GazeEstimator.
# ---------------------------------------------------------------------------
def _head_model():
    base = {
        1: (0.0, 0.0, 0.0),            # nose tip
        152: (0.0, -63.6, -12.5),      # chin
        33: (-43.3, 32.7, -26.0),      # left eye outer corner
        263: (43.3, 32.7, -26.0),      # right eye outer corner
        61: (-28.9, -28.9, -24.1),     # left mouth corner
        291: (28.9, -28.9, -24.1),     # right mouth corner
        133: (-17.0, 32.7, -26.0),     # left eye inner corner
        362: (17.0, 32.7, -26.0),      # right eye inner corner
        159: (-30.0, 42.7, -24.0),     # left eye top lid
        145: (-30.0, 22.7, -24.0),     # left eye bottom lid
        386: (30.0, 42.7, -24.0),      # right eye top lid
        374: (30.0, 22.7, -24.0),      # right eye bottom lid
    }
    return {idx: np.array(p, dtype=float) for idx, p in base.items()}


# Eye geometry (mm) used to place the iris from local gaze parameters.
LEFT_EYE_OUTER = np.array([-43.3, 32.7, -26.0], dtype=float)
LEFT_EYE_INNER = np.array([-17.0, 32.7, -26.0], dtype=float)
LEFT_EYE_TOP = np.array([-30.0, 42.7, -24.0], dtype=float)
LEFT_EYE_BOTTOM = np.array([-30.0, 22.7, -24.0], dtype=float)
RIGHT_EYE_INNER = np.array([17.0, 32.7, -26.0], dtype=float)
RIGHT_EYE_OUTER = np.array([43.3, 32.7, -26.0], dtype=float)
RIGHT_EYE_TOP = np.array([30.0, 42.7, -24.0], dtype=float)
RIGHT_EYE_BOTTOM = np.array([30.0, 22.7, -24.0], dtype=float)


def _ry(yaw):
    c, s = math.cos(yaw), math.sin(yaw)
    return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]], dtype=float)


def _rx(pitch):
    c, s = math.cos(pitch), math.sin(pitch)
    return np.array([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]], dtype=float)


def _rz(roll):
    c, s = math.cos(roll), math.sin(roll)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]], dtype=float)


def _normalize_deg(angle):
    while angle > 180:
        angle -= 360
    while angle < -180:
        angle += 360
    return angle


# ---------------------------------------------------------------------------
# Behavior profiles (per-verdict trajectory + event parameters)
# ---------------------------------------------------------------------------
def _default_profiles():
    return {
        "CLEAN": {
            # Markov states: (state_id, mu_yaw_deg, mu_pitch_deg, sigma_yaw, sigma_pitch, dwell_mean_s)
            "states": [("neutral", 0.0, 0.0, 1.2, 1.0, 25.0)],
            "start_state": "neutral",
            "transitions": {"neutral": [("neutral", 1.0)]},
            # gaze (iris) saccade magnitude, within-head
            "gaze_sigma": 0.05,
            "gaze_saccade_prob": 0.001,
            # face / environment
            "no_face_prob": 0.005,
            "multi_face_prob": 0.0,
            "multi_face_run_s": 0.0,
            # phone (side camera)
            "phone_turn_prob": 0.004,      # per-second chance of a 1-2 s head turn
            "phone_miss_prob": 0.05,       # detection miss rate
            "phone_angle": 35.0,           # deg the head turns when glancing at phone
            # audio
            "vad_mean": 0.05,
            "vad_sigma": 0.03,
            "external_voice_prob": 0.01,
            "lip_mean": 0.1,
            # events per session
            "focus_loss": (0, 1),
            "network_events": (3, 12),
            "network_integrity_prob": 0.0,
            "multi_monitor_prob": 0.0,
            "blacklist_prob": 0.0,
            "script_engine_prob": 0.0,
            "audio_alert_prob": 0.0,
            "object_prob": 0.0,
            "room_change_prob": 0.02,
            "confidence": (0, 15),
            "verdict": "CLEAN",
        },
        "SUSPICIOUS": {
            "states": [
                ("neutral", 0.0, 0.0, 3.0, 2.5, 12.0),
                ("turn_right", 38.0, 0.0, 3.0, 2.0, 2.0),
                ("turn_left", -38.0, 0.0, 3.0, 2.0, 2.0),
                ("pitch_down", 0.0, -33.0, 2.5, 4.0, 2.5),
            ],
            "start_state": "neutral",
            "transitions": {
                "neutral": [("neutral", 0.80), ("turn_right", 0.06), ("turn_left", 0.06), ("pitch_down", 0.08)],
                "turn_right": [("neutral", 0.5), ("turn_right", 0.5)],
                "turn_left": [("neutral", 0.5), ("turn_left", 0.5)],
                "pitch_down": [("neutral", 0.45), ("pitch_down", 0.55)],
            },
            "gaze_sigma": 0.09,
            "gaze_saccade_prob": 0.004,
            "no_face_prob": 0.02,
            "multi_face_prob": 0.01,
            "multi_face_run_s": 1.0,
            "phone_turn_prob": 0.02,
            "phone_miss_prob": 0.06,
            "phone_angle": 38.0,
            "vad_mean": 0.12,
            "vad_sigma": 0.06,
            "external_voice_prob": 0.06,
            "lip_mean": 0.25,
            "focus_loss": (2, 6),
            "network_events": (10, 30),
            "network_integrity_prob": 0.3,
            "multi_monitor_prob": 0.05,
            "blacklist_prob": 0.15,
            "script_engine_prob": 0.1,
            "audio_alert_prob": 0.2,
            "object_prob": 0.15,
            "room_change_prob": 0.25,
            "confidence": (30, 55),
            "verdict": "SUSPICIOUS",
        },
        "CHEATING": {
            "states": [
                ("neutral", 0.0, 0.0, 2.0, 2.0, 5.0),
                ("toward_phone", -42.0, 0.0, 3.0, 2.0, 6.0),
                ("desk", 0.0, -38.0, 3.0, 4.0, 6.0),
                ("off_screen", 70.0, -10.0, 4.0, 4.0, 3.0),
                ("helper_look", -30.0, 5.0, 3.0, 3.0, 3.0),
            ],
            "start_state": "neutral",
            "transitions": {
                "neutral": [("neutral", 0.40), ("toward_phone", 0.22), ("desk", 0.22), ("off_screen", 0.10), ("helper_look", 0.06)],
                "toward_phone": [("neutral", 0.30), ("toward_phone", 0.55), ("desk", 0.15)],
                "desk": [("neutral", 0.30), ("desk", 0.60), ("toward_phone", 0.10)],
                "off_screen": [("neutral", 0.4), ("off_screen", 0.5), ("toward_phone", 0.1)],
                "helper_look": [("neutral", 0.5), ("helper_look", 0.5)],
            },
            "gaze_sigma": 0.14,
            "gaze_saccade_prob": 0.008,
            "no_face_prob": 0.06,
            "multi_face_prob": 0.03,
            "multi_face_run_s": 2.0,
            "phone_turn_prob": 0.06,
            "phone_miss_prob": 0.05,
            "phone_angle": 42.0,
            "vad_mean": 0.2,
            "vad_sigma": 0.1,
            "external_voice_prob": 0.25,
            "lip_mean": 0.15,
            "focus_loss": (5, 12),
            "network_events": (20, 60),
            "network_integrity_prob": 0.5,
            "multi_monitor_prob": 0.2,
            "blacklist_prob": 0.6,
            "script_engine_prob": 0.4,
            "audio_alert_prob": 0.5,
            "object_prob": 0.5,
            "room_change_prob": 0.6,
            "confidence": (60, 100),
            "verdict": "CHEATING",
        },
    }


PROFILES = _default_profiles()


# ---------------------------------------------------------------------------
# Head pose trajectory (numpy, per-session). Markov dwell states + OU drift.
# ---------------------------------------------------------------------------
class HeadTrajectory:
    """Generates per-frame world head pose + gaze + face/audio signals."""

    def __init__(self, profile, fps=30, seed=0):
        self.profile = PROFILES[profile]
        self.fps = fps
        self.rng = np.random.default_rng(seed)

    def build(self, duration_s):
        n = int(round(duration_s * self.fps))
        p = self.profile
        states = {name: idx for idx, name in enumerate([s[0] for s in p["states"]])}

        yaw = np.zeros(n)
        pitch = np.zeros(n)
        roll = self.rng.normal(0, 0.5, n)

        # --- Markov dwell-state generation (vectorized over segments) ---
        state = p["start_state"]
        i = 0
        while i < n:
            dwell = max(3, int(round(self.rng.exponential(p["states"][states[state]][5]) * self.fps)))
            seg = min(dwell, n - i)
            mu_yaw = p["states"][states[state]][1]
            mu_pitch = p["states"][states[state]][2]
            s_yaw = p["states"][states[state]][3]
            s_pitch = p["states"][states[state]][4]

            # Ornstein-Uhlenbeck drift toward the state target.
            theta = 2.0
            dt = 1.0 / self.fps
            eps_y = self.rng.normal(0, 1, seg)
            eps_p = self.rng.normal(0, 1, seg)
            seg_yaw = np.zeros(seg)
            seg_pitch = np.zeros(seg)
            for k in range(1, seg):
                seg_yaw[k] = seg_yaw[k - 1] - theta * (seg_yaw[k - 1] - mu_yaw) * dt + s_yaw * math.sqrt(dt) * eps_y[k]
                seg_pitch[k] = seg_pitch[k - 1] - theta * (seg_pitch[k - 1] - mu_pitch) * dt + s_pitch * math.sqrt(dt) * eps_p[k]
            yaw[i:i + seg] = seg_yaw
            pitch[i:i + seg] = seg_pitch
            i += seg

            # transition to next state
            next_candidates = p["transitions"].get(state, [("neutral", 1.0)])
            names = [c[0] for c in next_candidates]
            weights = [c[1] for c in next_candidates]
            state = self.rng.choice(names, p=weights)

        # --- gaze (within-head iris saccades) ---
        gaze_lr = self.rng.normal(0, p["gaze_sigma"], n)
        gaze_ud = self.rng.normal(0, p["gaze_sigma"], n)
        # occasional saccade jumps
        saccade = self.rng.random(n) < p["gaze_saccade_prob"]
        jump_lr = self.rng.choice([-1.0, 1.0], n) * self.rng.uniform(0.5, 0.9, n)
        jump_ud = self.rng.choice([-1.0, 1.0], n) * self.rng.uniform(0.4, 0.8, n)
        gaze_lr = np.where(saccade, jump_lr, gaze_lr)
        gaze_ud = np.where(saccade, jump_ud, gaze_ud)
        gaze_lr = np.clip(gaze_lr, -1, 1)
        gaze_ud = np.clip(gaze_ud, -1, 1)

        # --- face count (run-based) ---
        face_count = np.ones(n, dtype=int)
        no_face = self.rng.random(n) < p["no_face_prob"]
        if p["multi_face_prob"] > 0:
            multi = self.rng.random(n) < p["multi_face_prob"]
        else:
            multi = np.zeros(n, dtype=bool)
        # expand no_face/multi runs to at least a few frames (0.3-2 s)
        for flag, min_run in ((no_face, max(6, int(0.4 * self.fps))), (multi, max(3, int(0.3 * self.fps)))):
            idx = np.flatnonzero(flag)
            for j in idx:
                face_count[j:j + min_run] = 0 if flag is no_face else 2
        face_count = np.where(face_count > 2, 2, face_count)

        # --- audio (VAD / lip) ---
        vad = np.clip(self.rng.normal(p["vad_mean"], p["vad_sigma"], n), 0, 1)
        lip = np.clip(self.rng.normal(p["lip_mean"], 0.06, n), 0, 1)

        return {
            "yaw": yaw, "pitch": pitch, "roll": roll,
            "gaze_lr": gaze_lr, "gaze_ud": gaze_ud,
            "face_count": face_count,
            "vad": vad, "lip": lip,
            "n": n, "fps": self.fps, "duration_s": duration_s,
        }


# ---------------------------------------------------------------------------
# Camera models (intrinsics + extrinsics in world coordinates)
# ---------------------------------------------------------------------------
class Webcam:
    """Frontal camera at world origin, optical axis +Z."""

    def __init__(self, width=640, height=480):
        self.width, self.height = width, height
        self.focal = float(width)
        self.cx, self.cy = width / 2.0, height / 2.0
        self.head_pose = HeadPoseEstimator()
        self.gaze = GazeEstimator()

    def project(self, points3):
        """points3: Nx3 world coords -> Nx2 image coords."""
        x, y, z = points3[:, 0], points3[:, 1], points3[:, 2]
        with np.errstate(divide="ignore", invalid="ignore"):
            u = self.cx + self.focal * x / z
            v = self.cy - self.focal * y / z
        return np.stack([u, v], axis=-1)

    def measure(self, model2d, frame_shape):
        """model2d: dict idx -> np.array([x,y]); returns (raw_yaw, raw_pitch, gaze_dict)."""
        landmarks = [np.array([0.0, 0.0])] * 474
        for idx, pt in model2d.items():
            landmarks[idx] = pt
        raw_yaw, raw_pitch = self.head_pose.estimate(landmarks, frame_shape)
        gaze_away, gaze = self.gaze.estimate(landmarks, frame_shape)
        return raw_yaw, raw_pitch, gaze_away, gaze


class SideCam:
    """Phone camera: look-at the candidate from a side offset. Returns 2D projections
    plus a geometric face-visibility flag (reproduces the runtime's 'profile vs frontal'
    phone signal)."""

    def __init__(self, position_cm, width=640, height=480):
        self.pos = np.asarray(position_cm, dtype=float) * 10.0  # cm -> mm
        self.width, self.height = width, height
        self.focal = float(width)
        self.cx, self.cy = width / 2.0, height / 2.0
        self.rot = None
        self.z_axis = None

    def aim_at(self, target_mm):
        z = target_mm - self.pos
        norm = np.linalg.norm(z)
        z = z / norm if norm > 0 else np.array([-1.0, 0.0, 0.0])
        up = np.array([0.0, 1.0, 0.0])
        x = np.cross(up, z)
        nx = np.linalg.norm(x)
        x = x / nx if nx > 0 else np.array([1.0, 0.0, 0.0])
        y = np.cross(z, x)
        self.z_axis = z
        self.rot = np.stack([x, y, z], axis=0)  # world -> camera rotation (rows)

    def project(self, points3):
        rel = points3 - self.pos
        cam = rel @ self.rot.T  # (N,3) in camera frame
        x, y, z = cam[:, 0], cam[:, 1], cam[:, 2]
        with np.errstate(divide="ignore", invalid="ignore"):
            u = self.cx + self.focal * x / z
            v = self.cy - self.focal * y / z
        return np.stack([u, v], axis=-1)

    def face_visible(self, head_center, nose_dir, threshold_deg=40.0):
        """Frontal-face visible to the phone iff the angle between the nose direction
        and the head->phone vector is small. Neutral pose (~45 deg) => profile => not
        visible; turning toward the phone => frontal => visible."""
        to_phone = self.pos - np.asarray(head_center)  # head -> phone vector
        n = np.linalg.norm(to_phone)
        if n == 0:
            return False
        to_phone = to_phone / n
        cos_ang = float(np.dot(nose_dir, to_phone))
        return math.degrees(math.acos(max(-1.0, min(1.0, cos_ang)))) < threshold_deg


def _solve_pnp_phone(pts2d, focal, cx, cy):
    """Parameterized 6-point solvePnP (mirrors gaze/head_pose.py but for phone intrinsics)."""
    pts_3d = np.array([
        (0.0, 0.0, 0.0), (0.0, 63.6, -12.5),
        (-43.3, -32.7, -26.0), (43.3, -32.7, -26.0),
        (-28.9, 28.9, -24.1), (28.9, 28.9, -24.1),
    ], dtype="double")
    idx = [1, 152, 33, 263, 61, 291]
    image_points = np.array([pts2d[i] for i in idx], dtype="double")
    cam = np.array([[focal, 0, cx], [0, focal, cy], [0, 0, 1]], dtype="double")
    ok, rvec, _ = cv2.solvePnP(pts_3d, image_points, cam, np.zeros((4, 1)), flags=cv2.SOLVEPNP_ITERATIVE)
    if not ok:
        return 0.0, 0.0
    rmat, _ = cv2.Rodrigues(rvec)
    angles, _, _, _, _, _ = cv2.RQDecomp3x3(rmat)
    return float(angles[1]), float(-angles[0])


# ---------------------------------------------------------------------------
# Per-session simulator
# ---------------------------------------------------------------------------
class SessionSimulator:
    """Simulates one session end-to-end and exposes per-frame measurements."""

    def __init__(self, profile="CLEAN", seed=0, fps=30, thresholds=None):
        if thresholds is None:
            thresholds = Thresholds()
        self.profile = PROFILES[profile]
        self.fps = fps
        self.rng = np.random.default_rng(seed)

        self.tri = thresholds.triangulation
        self.thresholds = thresholds
        self.screen_distance_cm = self.tri("screen_distance_cm", default=60.0)
        self.phone_x_cm = self.tri("phone_offset_x_cm", default=45.0)
        self.phone_z_cm = self.tri("phone_offset_z_cm", default=30.0)
        self.head_dist_cm = self.screen_distance_cm + 15.0  # candidate sits ~15 cm in front of screen

        self.webcam = Webcam()
        phone_pos = [self.phone_x_cm, 0.0, self.phone_z_cm]
        self.phone = SideCam(phone_pos)
        self.triangulator = GazeTriangulator(thresholds)
        self.fuser = ScoreFusion(thresholds)

        # Per-user head placement noise (each synthetic user sits slightly differently).
        self.head_center = np.array([0.0, 0.0, self.head_dist_cm], dtype=float) * 10.0  # mm
        self.head_center[0] += self.rng.normal(0, 3.0) * 10.0
        self.head_center[1] += self.rng.normal(0, 2.0) * 10.0
        self.phone.aim_at(self.head_center)

        # Calibration baseline: measured raw pose while looking straight (with noise).
        self.baseline_yaw, self.baseline_pitch = self._calibrate()

        self.smooth_yaw = 0.0
        self.smooth_pitch = 0.0
        self.raw_phone_yaw = 0.0
        self.raw_phone_pitch = 0.0

    def _world_from_state(self, yaw_deg, pitch_deg, roll_deg, gaze_lr, gaze_ud):
        """Returns (world3d, idxs, nose_dir): the head model points in world mm,
        the MediaPipe indices in sorted order, and the world-space nose direction."""
        yaw = math.radians(yaw_deg)
        pitch = math.radians(pitch_deg)
        roll = math.radians(roll_deg)
        R = _ry(yaw) @ _rx(pitch) @ _rz(roll)
        t = self.head_center

        model = _head_model()
        # place iris from gaze params (conjugate eye motion)
        l_ratio = np.clip(0.5 - gaze_lr * 0.45, 0.05, 0.95)
        r_ratio = np.clip(0.5 - gaze_lr * 0.45, 0.05, 0.95)
        v_ratio = np.clip(0.5 + gaze_ud * 0.45, 0.05, 0.95)
        lx = LEFT_EYE_OUTER[0] + l_ratio * (LEFT_EYE_INNER[0] - LEFT_EYE_OUTER[0])
        rx = RIGHT_EYE_INNER[0] + r_ratio * (RIGHT_EYE_OUTER[0] - RIGHT_EYE_INNER[0])
        ly = LEFT_EYE_TOP[1] - v_ratio * (LEFT_EYE_TOP[1] - LEFT_EYE_BOTTOM[1])
        ry = RIGHT_EYE_TOP[1] - v_ratio * (RIGHT_EYE_TOP[1] - RIGHT_EYE_BOTTOM[1])
        model[468] = np.array([lx, ly, -24.0])
        model[473] = np.array([rx, ry, -24.0])

        idxs = sorted(model)
        pts = np.stack([model[i] for i in idxs], axis=0)
        world3d = pts @ R.T + t  # world coords (mm)
        nose_dir = R @ np.array([0.0, 0.0, -1.0], dtype=float)  # head forward (nose)
        return world3d, idxs, nose_dir

    def _calibrate(self):
        yaws, pitches = [], []
        rng = np.random.default_rng(self.rng.integers(0, 2 ** 31))
        for _ in range(60):
            y, p, _, _ = self._measure_webcam(0.0, 0.0, 0.0, 0.0, 0.0)
            yaws.append(y)
            pitches.append(p)
        return float(np.mean(yaws)), float(np.mean(pitches))

    def _measure_webcam(self, yaw_deg, pitch_deg, roll_deg, gaze_lr, gaze_ud, jitter_px=0.6):
        world3d, idxs, _ = self._world_from_state(yaw_deg, pitch_deg, roll_deg, gaze_lr, gaze_ud)
        pts = self.webcam.project(world3d)
        pts = pts + self.rng.normal(0, jitter_px, pts.shape)
        model2d = {i: pts[n] for n, i in enumerate(idxs)}
        raw_yaw, raw_pitch, gaze_away, gaze = self.webcam.measure(model2d, (self.webcam.height, self.webcam.width))
        if raw_yaw is None:
            raw_yaw, raw_pitch = 0.0, 0.0
        return raw_yaw, raw_pitch, gaze_away, gaze

    def _measure_phone(self, yaw_deg, pitch_deg, roll_deg, gaze_lr, gaze_ud, jitter_px=1.0):
        world3d, idxs, nose_dir = self._world_from_state(yaw_deg, pitch_deg, roll_deg, gaze_lr, gaze_ud)
        pts = self.phone.project(world3d)
        pts = pts + self.rng.normal(0, jitter_px, pts.shape)
        model2d = {i: pts[n] for n, i in enumerate(idxs)}
        py, pp = _solve_pnp_phone(model2d, self.phone.focal, self.phone.cx, self.phone.cy)
        self.raw_phone_yaw, self.raw_phone_pitch = float(py), float(pp)
        visible = self.phone.face_visible(self.head_center, nose_dir)
        return py, pp, visible

    def _phone_visible_deg(self, yaw_deg, pitch_deg):
        """Cheap geometric phone-visibility (no solvePnP): angle between the nose
        direction and the head->phone vector."""
        yaw = math.radians(yaw_deg)
        pitch = math.radians(pitch_deg)
        nose_dir = np.array([
            -math.sin(yaw) * math.cos(pitch),
            math.sin(pitch),
            -math.cos(yaw) * math.cos(pitch),
        ], dtype=float)
        to_phone = self.phone.pos - self.head_center
        n = np.linalg.norm(to_phone)
        if n == 0:
            return 180.0
        to_phone = to_phone / n
        cos_ang = float(np.dot(nose_dir, to_phone))
        return math.degrees(math.acos(max(-1.0, min(1.0, cos_ang))))

    def raw_measure(self, yaw_deg, pitch_deg, roll_deg, gaze_lr, gaze_ud):
        """Full solvePnP measurement (expensive). Returns
        (raw_yaw, raw_pitch, gaze_away, gaze_dict, phone_visible)."""
        yaw_w = float(yaw_deg); pitch_w = float(pitch_deg); roll_w = float(roll_deg)
        g_lr = float(gaze_lr); g_ud = float(gaze_ud)
        raw_yaw, raw_pitch, gaze_away, gaze = self._measure_webcam(yaw_w, pitch_w, roll_w, g_lr, g_ud)
        _, _, phone_visible = self._measure_phone(yaw_w, pitch_w, roll_w, g_lr, g_ud)
        return raw_yaw, raw_pitch, gaze_away, gaze, bool(phone_visible)

    def raw_approx(self, yaw_deg, pitch_deg, roll_deg, gaze_lr, gaze_ud):
        """Cheap analytic approximation for violation-timing frames."""
        yaw_w = float(yaw_deg); pitch_w = float(pitch_deg)
        g_lr = float(gaze_lr); g_ud = float(gaze_ud)
        raw_yaw = yaw_w + float(self.rng.normal(0, 0.8))
        raw_pitch = pitch_w + float(self.rng.normal(0, 0.8))
        h_ratio = float(np.clip(0.5 - g_lr * 0.45, 0.05, 0.95))
        v_ratio = float(np.clip(0.5 + g_ud * 0.45, 0.05, 0.95))
        direction = "CENTER"
        gaze_away = False
        if h_ratio < 0.42:
            gaze_away, direction = True, "RIGHT"
        elif h_ratio > 0.58:
            gaze_away, direction = True, "LEFT"
        if v_ratio < 0.40:
            gaze_away, direction = True, "UP"
        elif v_ratio > 0.60:
            gaze_away, direction = True, "DOWN"
        gaze = {"h_ratio": h_ratio, "v_ratio": v_ratio, "direction": direction}
        phone_visible = self._phone_visible_deg(yaw_w, pitch_w) < 40.0
        return raw_yaw, raw_pitch, gaze_away, gaze, bool(phone_visible)

    def smooth(self, raw_yaw, raw_pitch):
        """Calibration baseline subtraction + EMA smoothing (mirrors proctor_thread)."""
        yaw_diff = _normalize_deg(float(raw_yaw) - self.baseline_yaw)
        pitch_diff = _normalize_deg(float(raw_pitch) - self.baseline_pitch)
        alpha = 0.15
        self.smooth_yaw = alpha * yaw_diff + (1 - alpha) * self.smooth_yaw
        self.smooth_pitch = alpha * pitch_diff + (1 - alpha) * self.smooth_pitch
        return self.smooth_yaw, self.smooth_pitch

    def build_metric(self, yaw, pitch, raw_yaw, raw_pitch, gaze, phone_visible, state):
        """Assembles the METRICS row the runtime would log for this frame."""
        yaw_th = self.thresholds.rules("yaw_threshold_deg", default=35.0)
        pitch_th = self.thresholds.rules("pitch_threshold_deg", default=30.0)
        head_away = abs(float(yaw)) > yaw_th or abs(float(pitch)) > pitch_th
        gaze_away = bool(gaze.get("direction", "CENTER") != "CENTER")

        triangulation = None
        try:
            triangulation = self.triangulator.triangulate(
                float(yaw), float(pitch), phone_face_detected=bool(phone_visible))
        except Exception:
            triangulation = None

        fused = self.fuser.fuse({
            "gaze_away": 1.0 if gaze_away else 0.0,
            "head_away": 1.0 if head_away else 0.0,
            "phone_face": 1.0 if phone_visible else 0.0,
            "multi_face": 1.0 if int(state["face_count"]) > 1 else 0.0,
            "no_face": 1.0 if int(state["face_count"]) == 0 else 0.0,
            "object": 1.0 if state.get("object_detected", False) else 0.0,
            "audio": 1.0 if float(state["vad"]) > 0.5 else 0.0,
        })

        return {
            "gaze_h": round(float(gaze.get("h_ratio", 0.5)), 4),
            "gaze_v": round(float(gaze.get("v_ratio", 0.5)), 4),
            "head_yaw": round(float(raw_yaw), 2),
            "head_pitch": round(float(raw_pitch), 2),
            "yaw_diff": round(float(yaw), 2),
            "pitch_diff": round(float(pitch), 2),
            "face_count": int(state["face_count"]),
            "phone_face": 1 if phone_visible else 0,
            "phone_yaw": round(float(self.raw_phone_yaw), 2),
            "phone_pitch": round(float(self.raw_phone_pitch), 2),
            "gaze_direction": gaze.get("direction", "CENTER"),
            "screen_region": triangulation["screen_region"] if triangulation else "OFF_SCREEN",
            "on_screen": 1 if (triangulation and triangulation["on_screen"]) else 0,
            "looking_at_phone": 1 if (triangulation and triangulation["looking_at_phone"]) else 0,
            "phone_distance_cm": round(triangulation["phone_distance_cm"], 2) if triangulation else -1.0,
            "vad_prob": round(float(state["vad"]), 4),
            "lip_prob": round(float(state["lip"]), 4),
            "fused_score": fused["score"],
            "fused_status": fused["status"],
            "fused_reasons": fused["reasons"],
            "head_away": int(head_away),
            "gaze_away": int(gaze_away),
            "is_looking_away": int(head_away or gaze_away),
        }

    def frame(self, state, phone_turn_active=False, force_measure=True):
        """
        Advances one frame. Returns the METRICS dict the runtime would produce,
        or None for a non-measurement frame (force_measure=False).
        """
        yaw_w = float(state["yaw"])
        pitch_w = float(state["pitch"])
        roll_w = float(state["roll"])
        g_lr = float(state["gaze_lr"])
        g_ud = float(state["gaze_ud"])

        if force_measure:
            raw_yaw, raw_pitch, gaze_away, gaze, phone_visible = self.raw_measure(yaw_w, pitch_w, roll_w, g_lr, g_ud)
        else:
            raw_yaw, raw_pitch, gaze_away, gaze, phone_visible = self.raw_approx(yaw_w, pitch_w, roll_w, g_lr, g_ud)

        if phone_turn_active:
            phone_visible = True

        yaw, pitch = self.smooth(raw_yaw, raw_pitch)
        return self.build_metric(yaw, pitch, raw_yaw, raw_pitch, gaze, phone_visible, state)
