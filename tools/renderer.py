"""
3D Exam-Scene Renderer (tools/renderer.py)

Renders a photoreal-ish webcam frame of a seated examinee from the SAME 3D scene
the world simulator measures:

    - Head: MediaPipe canonical_face_model.obj (468 verts / 898 tris) scaled to mm,
      reflected into the simulator's convention (+z = back of head), rotated by the
      same yaw/pitch/roll and translated to the same head_center, then rendered with
      a fast software rasterizer (per-triangle normal shading, back-face culling,
      painter's depth order, shade-bucket fillPoly).
    - Eyes / iris: placed at the projected iris positions (model 468/473) so gaze
      direction is visible, matching what GazeEstimator measures.
    - Body: shaded shoulders/torso behind the head.
    - Room: lit back-wall, floor, desk and window light plane.
    - Post: deterministic sensor noise + vignette.

All geometry lives in the simulator's world frame (camera at origin, +Z toward the
candidate); projection here uses the CORRECT pinhole (v = cy - f*y/z) so rendered
frames are upright webcam views (y-down image coords, like real camera output).

Everything is pure numpy + OpenCV (no GPU, no external 3D engine) and fully
deterministic for a given seed.
"""

import math
import os

import cv2
import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CANONICAL_OBJ = os.path.join(_ROOT, "assets", "canonical_face_model.obj")

# Face metrics used to align the canonical model (units ~ mm).
_FACE_WIDTH_MM = 86.6   # our eye-corner distance 33<->263 is ~86.6 mm
_CANONICAL_EYE_SPAN = 8.8  # canonical eye-corner distance in model units


def _load_obj(path):
    verts, tris = [], []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            p = line.split()
            if not p:
                continue
            if p[0] == "v":
                verts.append([float(x) for x in p[1:4]])
            elif p[0] == "f":
                tris.append([int(x.split("/")[0]) - 1 for x in p[1:4]])
    return np.asarray(verts, dtype=np.float64), np.asarray(tris, dtype=np.int64)


def _align_to_mm(V):
    """Scale to mm, reflect +z to match the simulator (nose at origin, +z = back)."""
    V = V * (_FACE_WIDTH_MM / _CANONICAL_EYE_SPAN)
    V[:, 2] = -V[:, 2]
    V = V - V[1]  # nose tip at origin
    return V


def _face_normals(V, T):
    a, b, c = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
    n = np.cross(b - a, c - a)
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    return n / np.maximum(ln, 1e-12)


def _ry(yaw):
    c, s = math.cos(yaw), math.sin(yaw)
    return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]], dtype=float)


def _rx(pitch):
    c, s = math.cos(pitch), math.sin(pitch)
    return np.array([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]], dtype=float)


def _rz(roll):
    c, s = math.cos(roll), math.sin(roll)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]], dtype=float)


def _build_room(width, height, seed):
    """Lit room: gradient wall, window light, baseboard, desk surface."""
    rng = np.random.default_rng(seed)
    img = np.zeros((height, width, 3), dtype=np.uint8)
    wall = np.array([58, 62, 70], dtype=np.float32)   # BGR
    grad = np.linspace(1.0, 0.80, height, dtype=np.float32)[:, None]
    for ch in range(3):
        img[:, :, ch] = np.clip(wall[ch] * grad, 0, 255).astype(np.uint8)
    wx, wy, ww, wh = int(width * 0.05), int(height * 0.06), int(width * 0.24), int(height * 0.30)
    cv2.rectangle(img, (wx, wy), (wx + ww, wy + wh), (150, 158, 172), -1)
    cv2.rectangle(img, (wx + 8, wy + 8), (wx + ww - 8, wy + wh - 8), (178, 188, 204), -1)
    cv2.line(img, (wx + ww // 2, wy), (wx + ww // 2, wy + wh), (140, 148, 162), 2)
    cv2.line(img, (wx, wy + wh // 2), (wx + ww, wy + wh // 2), (140, 148, 162), 2)
    px, py, pw, ph = int(width * 0.72), int(height * 0.08), int(width * 0.20), int(height * 0.26)
    cv2.rectangle(img, (px, py), (px + pw, py + ph), (46, 44, 42), -1)
    cv2.rectangle(img, (px + 5, py + 5), (px + pw - 5, py + ph - 5), (64, 62, 58), -1)
    desk_y = int(height * 0.68)
    cv2.rectangle(img, (0, desk_y), (width, height), (34, 30, 26), -1)
    cv2.rectangle(img, (0, desk_y), (width, desk_y + 5), (52, 46, 38), -1)
    cv2.line(img, (0, desk_y + 5), (width, desk_y + 5), (80, 70, 56), 2)
    # faint floor perspective lines on the desk
    for k in range(4):
        x = int(width * (0.5 + 0.45 * (k - 1.5)))
        cv2.line(img, (x, desk_y + 5), (int(width / 2 + (x - width / 2) * 0.25), height), (52, 46, 38), 1)
    return img, desk_y


class SceneRenderer:
    """Renders the simulated 3D scene to a webcam frame for a given pose."""

    SKIN = (200, 170, 148)
    HAIR = (42, 34, 30)
    CLOTHES = (30, 32, 40)

    def __init__(self, width=640, height=480, seed=0):
        self.w, self.h = width, height
        self.seed = int(seed)
        V, T = _load_obj(_CANONICAL_OBJ)
        self.verts = _align_to_mm(V)
        self.tris = T
        self.tri_normals = _face_normals(self.verts, T)
        self.light = np.array([0.35, 0.60, -0.72], dtype=float)
        self.light /= np.linalg.norm(self.light)
        self.ambient, self.diffuse = 0.45, 0.62
        self.n_shades = 32
        self.room, self.desk_y = _build_room(width, height, seed)
        self._build_luts()

    def _build_luts(self):
        skin = np.array(self.SKIN, dtype=np.float64)
        cloth = np.array(self.CLOTHES, dtype=np.float64)
        s = self.n_shades
        self.skin_lut = np.zeros((s + 1, 3), dtype=np.uint8)
        self.cloth_lut = np.zeros((s + 1, 3), dtype=np.uint8)
        for i in range(s + 1):
            f = self.ambient + self.diffuse * (i / max(s, 1))
            self.skin_lut[i] = np.clip(skin * f, 0, 255)
            self.cloth_lut[i] = np.clip(cloth * f, 0, 255)

    # ------------------------------------------------------------------
    def _project(self, cam, pts3):
        x, y, z = pts3[:, 0], pts3[:, 1], pts3[:, 2]
        with np.errstate(divide="ignore", invalid="ignore"):
            u = cam.cx + cam.focal * x / z
            v = cam.cy - cam.focal * y / z
        return np.stack([u, v], axis=-1)

    def _draw_mesh(self, out, cam, verts_world, tris, tri_normals):
        """Painter's-order shaded triangle fill into the buffer `out` (int32 shade idx)."""
        uv = self._project(cam, verts_world)
        if tris is None:
            return
        a, b, c = uv[tris[:, 0]], uv[tris[:, 1]], uv[tris[:, 2]]
        area2 = (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0])
        depth = verts_world[tris].mean(axis=1)[:, 2]
        # view dir from head toward camera = camera - head ~ -head (camera at origin)
        ndot = tri_normals @ (-verts_world.mean(axis=0) / np.maximum(np.linalg.norm(verts_world.mean(axis=0)), 1e-9))
        keep = (area2 > 1e-3) & (ndot > 0.05)
        if not keep.any():
            return
        idx = np.where(keep)[0]
        order = np.argsort(depth[idx])[::-1]  # far -> near
        idx = idx[order]
        shade = self.ambient + self.diffuse * np.clip(tri_normals[idx] @ self.light, 0, 1)
        shade_i = np.clip((shade / (self.ambient + self.diffuse) * self.n_shades).astype(int), 0, self.n_shades)
        tri_uv = uv[tris[idx]].reshape(-1, 1, 3, 2).astype(np.int32)
        for lvl in np.unique(shade_i):
            sel = np.where(shade_i == lvl)[0]
            cv2.fillPoly(out, tri_uv[sel], int(lvl))

    # ------------------------------------------------------------------
    def render(self, cam, yaw_deg, pitch_deg, roll_deg,
               head_center, iris_l_3d, iris_r_3d, eye_l_3d, eye_r_3d,
               face_count=1, seed=None):
        """
        Renders one frame.

        iris_l_3d / iris_r_3d / eye_l_3d / eye_r_3d are WORLD (mm) points for the
        irises and outer eye corners; they are projected here with the renderer's
        correct pinhole so the eyes sit exactly where the scene says. Returns an
        8-bit BGR frame.
        """
        rng = np.random.default_rng(self.seed if seed is None else seed)
        R = _ry(math.radians(yaw_deg)) @ _rx(math.radians(pitch_deg)) @ _rz(math.radians(roll_deg))
        verts_world = self.verts @ R.T + np.asarray(head_center)
        tri_normals = self.tri_normals @ R.T

        out = self.room.copy()
        buf = np.full((self.h, self.w), -1, dtype=np.int32)

        # --- torso (world-static, behind head) ---
        neck = np.asarray(head_center).copy()
        neck[1] -= 62.0
        neck_uv = self._project(cam, neck[None, :])[0]
        hx, neck_y = int(neck_uv[0]), int(neck_uv[1])
        head_w = self.w / 6.0
        sh_w = int(head_w * 2.4)
        top = neck_y + int(head_w * 0.35)
        mask = np.zeros((self.h, self.w), np.uint8)
        cv2.ellipse(mask, (hx, top), (sh_w, int(head_w * 0.9)), 0, 0, 180, 255, -1)
        cv2.rectangle(mask, (hx - sh_w, top), (hx + sh_w, self.h), 255, -1)
        cv2.ellipse(mask, (hx, neck_y), (int(head_w * 0.30), int(head_w * 0.18)), 0, 0, 360, 255, -1)
        mask = cv2.GaussianBlur(mask, (0, 0), 6)
        m = (mask.astype(np.float32) / 255.0)[..., None]
        body = np.zeros_like(self.room, dtype=np.float32)
        for ch in range(3):
            body[:, :, ch] = self.CLOTHES[ch]
        yy = np.arange(self.h, dtype=np.float32)[:, None]
        body *= np.clip(0.72 + 0.45 * (yy - top) / max(self.h - top, 1), 0.72, 1.35)[..., None]
        out[:] = (out.astype(np.float32) * (1.0 - m) + body * m).astype(np.uint8)

        # --- head mesh ---
        self._draw_mesh(buf, cam, verts_world, self.tris, tri_normals)

        # hair cap: dark ellipse over the head top, painted over the mesh
        top_uv = self._project(cam, verts_world[10][None, :])[0]
        hw_px = 0.5 * np.linalg.norm(
            self._project(cam, verts_world[234][None, :])[0] - self._project(cam, verts_world[454][None, :])[0])
        hair_mask = np.zeros_like(buf, dtype=np.uint8)
        cv2.ellipse(hair_mask, (int(top_uv[0]), int(top_uv[1])),
                    (int(max(hw_px, 6)), int(max(hw_px * 0.55, 6))), 0, 180, 360, 255, -1)
        cv2.ellipse(hair_mask, (int(top_uv[0]), int(top_uv[1])),
                    (int(max(hw_px * 1.15, 6)), int(max(hw_px * 0.8, 6))), 0, 200, 340, 255, -1)
        hair_mask = cv2.GaussianBlur(hair_mask, (0, 0), 4)
        hair = np.array(self.HAIR, dtype=np.uint8)
        out[hair_mask > 0] = hair

        # composite head (shaded) over the scene
        head_mask = buf >= 0
        if head_mask.any():
            out[head_mask] = self.skin_lut[np.clip(buf[head_mask], 0, self.n_shades)]

        # --- eyes: sclera + iris (gaze-visible) ---
        self._draw_eye(out, self._project(cam, np.asarray(eye_l_3d)[None, :])[0],
                       self._project(cam, np.asarray(iris_l_3d)[None, :])[0])
        self._draw_eye(out, self._project(cam, np.asarray(eye_r_3d)[None, :])[0],
                       self._project(cam, np.asarray(iris_r_3d)[None, :])[0])

        return self._finish(out, rng)

    def _draw_eye(self, out, corner_uv, iris_uv):
        """Draws sclera + iris at the projected positions."""
        x0, y0 = float(corner_uv[0]), float(corner_uv[1])
        xi, yi = float(iris_uv[0]), float(iris_uv[1])
        if not (0 <= xi < self.w and 0 <= yi < self.h):
            return
        r = max(4.0, self.w * 0.012)
        scl_w = r * 1.9
        cv2.ellipse(out, (int((x0 + xi) / 2), int((y0 + yi) / 2)),
                    (int(scl_w), int(r * 0.85)), 0, 0, 360, (235, 235, 235), -1)
        cv2.circle(out, (int(xi), int(yi)), int(r * 0.62), (42, 40, 38), -1)
        cv2.circle(out, (int(xi), int(yi)), int(r * 0.26), (230, 230, 230), -1)

    def _finish(self, img, rng):
        img = img.astype(np.float32)
        img += rng.normal(0, 2.0, img.shape)
        yy, xx = np.mgrid[0:self.h, 0:self.w]
        r = np.sqrt((xx - self.w / 2.0) ** 2 + (yy - self.h / 2.0) ** 2)
        r = np.clip(r / (0.72 * max(self.w, self.h)), 0.0, 1.0)
        img *= (1.0 - 0.40 * r[..., None])
        return np.clip(img, 0, 255).astype(np.uint8)
