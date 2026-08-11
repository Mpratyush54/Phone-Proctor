"""
Blender renderer (tools/renderers/blender_renderer.py)

Renders a photoreal webcam frame of a seated candidate using Blender (bpy)
with a CC0 3D head scan + PBR materials. This is the "realistic human/face
model + camera + lighting + materials -> rendered RGB" stage of the pipeline.

Coordinate mapping (to match base.Camera / gaze/head_pose.py):
    Blender camera sits at origin looking down -Z. The head is placed at
    z = -DISTANCE so it is in front of the camera, and the rendered image
    follows webcam convention (u = cx + f*x/z, v = cy - f*y/z with +Z toward
    the candidate, +X right, +Y up, v increasing downward).

Intrinsics: focal_px == width (640) => lens = 36mm at sensor 36mm.

Rendering engine: EEVEE (fast, OpenGL) with Cycles-CUDA as an option.
The bpy import is slow, so use get_renderer() for a cached instance.
"""

import math
import os
import threading

import numpy as np

from tools.renderers.base import BaseRenderer

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DEFAULT_SCENE = os.path.join(
    _ROOT, "assets", "head", "scanstore", "Blender", "Blender Scene.blend")
_SENSOR_W = 36.0
_DISTANCE_M = 0.75

_lock = threading.Lock()
_cached = None


def _ry(yaw):
    c, s = math.cos(yaw), math.sin(yaw)
    return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]], dtype=float)


def _rx(pitch):
    c, s = math.cos(pitch), math.sin(pitch)
    return np.array([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]], dtype=float)


def _rz(roll):
    c, s = math.cos(roll), math.sin(roll)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]], dtype=float)


def _euler_from_matrix(R):
    """Rotation matrix -> XYZ euler (radians), Blender convention."""
    sy = math.sqrt(max(R[0, 0] ** 2 + R[1, 0] ** 2, 1e-12))
    if sy > 1e-6:
        x = math.atan2(R[2, 1], R[2, 2])
        y = math.atan2(-R[2, 0], sy)
        z = math.atan2(R[1, 0], R[0, 0])
    else:
        x = math.atan2(-R[1, 2], R[1, 1])
        y = math.atan2(-R[2, 0], sy)
        z = 0.0
    return (x, y, z)


class BlenderRenderer(BaseRenderer):
    """Renders frames through a persistent Blender scene."""

    def __init__(self, width=640, height=480, seed=0,
                 scene_path=None, engine="EEVEE", lens=None,
                 device="GPU"):
        import bpy

        super().__init__(width, height, seed)
        self._bpy = bpy
        self.engine = engine
        self.device = device
        self.scene_path = scene_path or _DEFAULT_SCENE
        self.lens = lens or (_SENSOR_W * width / 640.0)

        self._build_scene()
        self._set_engine()

    # ------------------------------------------------------------------
    def _build_scene(self):
        bpy = self._bpy
        bpy.ops.wm.open_mainfile(filepath=self.scene_path)
        self.scene = bpy.context.scene
        self.scene.render.resolution_x = self.width
        self.scene.render.resolution_y = self.height

        for o in list(bpy.data.objects):
            if o.type in ("CAMERA", "LIGHT"):
                bpy.data.objects.remove(o, do_unlink=True)

        self.head_objs = []
        for o in list(bpy.data.objects):
            if o.type == "MESH":
                o.location = (0.0, 0.0, 0.0)
                o.rotation_euler = (0.0, 0.0, 0.0)
                self.head_objs.append(o)
        # Normalize object scale (scene is baked at 100x -> real meters).
        bpy.context.view_layer.objects.active = self.head_objs[0]
        for o in self.head_objs:
            o.select_set(True)
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        self._rescale_mesh_to_meters()
        bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="BOUNDS")
        bpy.context.view_layer.update()

        # Determine head bounds so we can frame the face.
        xs, ys, zs = [], [], []
        for o in self.head_objs:
            import mathutils

            deps = bpy.context.evaluated_depsgraph_get()
            me = o.evaluated_get(deps)
            bb = [o.matrix_world @ mathutils.Vector(v) for v in me.bound_box]
            xs += [v[0] for v in bb]
            ys += [v[1] for v in bb]
            zs += [v[2] for v in bb]
        self.head_bounds = (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))

        # Camera at origin, default orientation looks down -Z.
        cam = bpy.data.cameras.new("RigCam")
        cam.lens = self.lens
        cam.sensor_width = _SENSOR_W
        cam_obj = bpy.data.objects.new("RigCam", cam)
        bpy.context.scene.collection.objects.link(cam_obj)
        self.cam_obj = cam_obj
        self.scene.camera = cam_obj
        self._add_lights()

    def _rescale_mesh_to_meters(self):
        """Baked scene is at 100x real meters; shrink mesh data to meters."""
        import mathutils

        bpy = self._bpy
        for o in self.head_objs:
            o.data.transform(mathutils.Matrix.Scale(0.01, 4))
            o.data.update()

    def _add_lights(self):
        bpy = self._bpy
        for loc, power in [
            ((2.0, 2.0, 2.0), 400.0),
            ((-2.0, -1.0, 2.0), 150.0),
            ((0.0, 0.0, 3.0), 100.0),
        ]:
            lamp = bpy.data.lights.new(f"Light_{int(power)}", "POINT")
            lamp.energy = power
            obj = bpy.data.objects.new(lamp.name, lamp)
            bpy.context.scene.collection.objects.link(obj)
            obj.location = loc

    def _set_engine(self):
        bpy = self._bpy
        if self.engine == "CYCLES":
            self.scene.render.engine = "CYCLES"
            self.scene.cycles.device = "GPU" if self.device == "GPU" else "CPU"
            try:
                prefs = bpy.context.preferences.addons["cycles"].preferences
                prefs.compute_device_type = "CUDA"
                prefs.get_devices()
                for d in prefs.devices:
                    d.use = True
            except Exception:
                pass
            self.scene.cycles.samples = 32
        else:
            self.scene.render.engine = "BLENDER_EEVEE"

    # ------------------------------------------------------------------
    def render(self, yaw_deg, pitch_deg, roll_deg, head_center, gaze=None, visible=True):
        import tempfile

        import cv2

        bpy = self._bpy
        hc = np.asarray(head_center, dtype=float) / 1000.0
        R = _ry(math.radians(yaw_deg)) @ _rx(math.radians(pitch_deg)) @ _rz(math.radians(roll_deg))
        eul = _euler_from_matrix(R)

        for o in self.head_objs:
            o.rotation_euler = eul
            o.location = (float(hc[0]), float(hc[1]), float(-hc[2]))
            o.hide_render = not visible

        fd, path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        self.scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
        bgr = cv2.imread(path)
        os.remove(path)
        if bgr is None:
            raise RuntimeError("Blender render produced no image")
        return bgr

    def close(self):
        pass


def get_renderer(**kwargs):
    """Builds (once) and returns the shared BlenderRenderer instance."""
    global _cached
    with _lock:
        if _cached is None:
            _cached = BlenderRenderer(**kwargs)
        return _cached
