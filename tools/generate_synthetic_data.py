"""
Synthetic Proctoring Data Generator (tools/generate_synthetic_data.py)

Creates deterministic, resumable, multiprocess synthetic exam sessions that a
downstream trainer can consume without any code changes:

    data/synthetic/<sid>/events.jsonl       JSONL (INFO / VIOLATION / NETWORK / AUDIO / METRICS)
    data/synthetic/<sid>/FINAL_REPORT.md    emoji-free verdict report
    data/synthetic/<sid>/.done              completion marker (written last)

Sessions are simulated with the geometry-driven world simulator
(tools/world_simulator.py) which pushes the 3D scene through the SAME production
math the runtime uses (HeadPoseEstimator, GazeEstimator, GazeTriangulator,
ScoreFusion), so synthetic METRICS carry the same camera/calibration artifacts.

Resume: a session whose <sid>/.done exists is skipped. Because sids are
deterministic (seed + index), rerunning the same command resumes exactly where
it stopped and reproduces identical output.

Usage:
    python tools/generate_synthetic_data.py --total-events 12000000 --workers 4 --seed 42
    python tools/generate_synthetic_data.py --total-events 20000 --smoke
    python tools/generate_synthetic_data.py --total-events 12000000 --rich-sessions 200 --face-crops data/face_crops
"""

import argparse
import glob
import json
import math
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timedelta

import cv2
import numpy as np

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from tools.world_simulator import PROFILES, HeadTrajectory, SessionSimulator

BASE_DATE = datetime(2026, 1, 1, 0, 0, 0)

DURATION_RANGES = {
    "CLEAN": (1800, 3600),
    "SUSPICIOUS": (1200, 2700),
    "CHEATING": (900, 2400),
}

FOCUS_TITLES = [
    "Microsoft Edge - Exam Portal",
    "Chrome - Online Test",
    "Firefox - Proctored Exam",
    "Notepad - Exam Notes",
    "Word - Question Paper",
    "Exam Application",
]

BLACKLIST_PROCS = ["cheat_engine.exe", "teamviewer.exe", "anydesk.exe", "taskmgr.exe", "whatsapp.exe", "telegram.exe"]
SCRIPT_ENGINES = ["cmd.exe", "powershell.exe", "wscript.exe", "cscript.exe", "autohotkey.exe"]
OBJECTS = [
    '{"object": "cell phone", "confidence": 0.92, "bbox": [150, 90, 210, 340]}',
    '{"object": "book", "confidence": 0.87, "bbox": [320, 120, 400, 300]}',
    '{"object": "remote", "confidence": 0.78, "bbox": [40, 200, 110, 260]}',
    '{"object": "tv", "confidence": 0.95, "bbox": [10, 10, 200, 150]}',
]
ROOM_NOTES = [
    "Room scene change detected (diff=0.21)",
    "Room scene change detected (diff=0.34)",
    "Second person detected in room",
    "New object in room: cell phone",
    "New object in room: book",
]
TRAFFIC_LOGS = [
    "New Conn: chrome.exe > 142.250.191.46:443",
    "New Conn: msedge.exe > 20.190.160.12:443",
    "New Conn: teams.exe > 52.112.8.10:3478",
    "New Conn: onedrive.exe > 13.107.42.12:443",
    "New Conn: firefox.exe > 34.107.221.82:443",
    "New Conn: winupdate.exe > 40.119.21.7:443",
]
AUDIO_TRANSCRIPTS = [
    "what is the answer to question four",
    "make sure you check your answers",
    "look at the screen please",
    "i need help with the next question",
    "can you read the instructions out loud",
    "what time does the exam end",
    "i did not understand the second part",
    "is question seven multiple choice",
    "please repeat that one more time",
    "how many marks is question three",
    "i think i need more time",
    "did you see the last question",
    "is the internet working on your side",
    "which formula should i use here",
    "the question is not loading on my screen",
    "okay i have it now thanks",
    "sorry i was looking at my notes",
    "one moment i am checking the next page",
]


def sid_for(seed, index):
    return f"S{seed:04d}N{index:06d}"


def rng_for(seed, index):
    return np.random.default_rng((int(seed), int(index)))


def make_record(sid, ts, etype, data, image_path=None):
    return {
        "timestamp": ts.isoformat(),
        "session_id": sid,
        "type": etype,
        "image_path": image_path,
        "data": data,
    }


class _Timers:
    """Deterministic temporal rule state (frame-index based, mirrors RuleEngine)."""

    def __init__(self):
        self.look_away_start = None
        self.multi_start = None
        self.face_missing_start = None
        self.last_look_away = -10 ** 9
        self.last_phone_turn = -10 ** 9
        self.last_triangulation = -10 ** 9
        self.last_fusion = -10 ** 9
        self.last_multi_emit = -10 ** 9
        self.last_face_missing = -10 ** 9


def _pick_profile(rng, profiles):
    names = [p["name"] for p in profiles]
    weights = [p["weight"] for p in profiles]
    return rng.choice(names, p=weights)


def _async_events(sid, profile, duration_s, start_time, rng, audio_dir=None, audio_engine=None):
    """Scheduled (non-pose) events: focus loss, network, blacklist, audio, etc."""
    p = profile
    events = []
    fps = 30

    def at(t_sec, etype, data):
        events.append(make_record(sid, start_time + timedelta(seconds=float(t_sec)), etype, data))

    # Focus loss
    n_focus = rng.integers(p["focus_loss"][0], p["focus_loss"][1] + 1)
    for _ in range(n_focus):
        at(rng.uniform(30, duration_s - 20), "VIOLATION", f"Focus Lost: {rng.choice(FOCUS_TITLES)}")

    # Network traffic logs (NETWORK type)
    n_net = rng.integers(p["network_events"][0], p["network_events"][1] + 1)
    for _ in range(n_net):
        at(rng.uniform(5, duration_s - 5), "NETWORK", rng.choice(TRAFFIC_LOGS))

    # Network integrity violations (sparser)
    if rng.random() < p.get("network_integrity_prob", 0.0):
        n_int = rng.integers(1, 4)
        for _ in range(n_int):
            msg = rng.choice([
                "NETWORK_INTEGRITY: Not connected to allowed hotspot",
                "NETWORK_INTEGRITY: Data spike: UP 124 KB/s / DOWN 640 KB/s",
                "NETWORK_INTEGRITY: Device count changed (expected 1-3, found 5)",
            ])
            at(rng.uniform(10, duration_s - 10), "VIOLATION", msg)

    # Blacklisted apps
    if rng.random() < p["blacklist_prob"]:
        for _ in range(rng.integers(1, 4)):
            proc = rng.choice(BLACKLIST_PROCS)
            ip = f"{rng.integers(1, 255)}.{rng.integers(0, 255)}.{rng.integers(0, 255)}.{rng.integers(1, 255)}"
            port = rng.integers(1024, 65535)
            at(rng.uniform(10, duration_s - 10), "VIOLATION", f"Blacklisted App: {proc} -> {ip}:{port}")

    # Script engines
    if rng.random() < p["script_engine_prob"]:
        for _ in range(rng.integers(1, 3)):
            at(rng.uniform(10, duration_s - 10), "VIOLATION", f"Script Engine Detected: {rng.choice(SCRIPT_ENGINES)}")

    # Audio alerts
    if rng.random() < p["audio_alert_prob"]:
        n_audio = rng.integers(1, 5)
        for _ in range(n_audio):
            at(rng.uniform(10, duration_s - 10), "VIOLATION", "Audio Alert: Noise at PC not on Phone")
        # Structured AUDIO records with real TTS clips when synthesis is enabled
        n_voice = int(rng.integers(0, 3))
        if n_voice and audio_engine and audio_dir:
            os.makedirs(audio_dir, exist_ok=True)
            from tools.audio_synth import synth_clip

            for _ in range(n_voice):
                transcript = rng.choice(AUDIO_TRANSCRIPTS)
                fname = f"audio_{int(rng.integers(0, 2 ** 31))}.wav"
                wav_path = os.path.join(audio_dir, fname)
                ok = synth_clip(transcript, wav_path, engine=audio_engine)
                if ok:
                    at(rng.uniform(10, duration_s - 10), "AUDIO", {
                        "msg": "Audio Alert: External Voice Detected",
                        "path": f"audio/{fname}",
                        "transcript": transcript,
                    })
        else:
            for _ in range(n_voice):
                at(rng.uniform(10, duration_s - 10), "AUDIO", {
                    "msg": "Audio Alert: Noise at PC not on Phone",
                    "path": f"audio/{rng.integers(1, 99)}.wav",
                    "transcript": rng.choice(AUDIO_TRANSCRIPTS),
                })

    # Object detections
    if rng.random() < p["object_prob"]:
        for _ in range(rng.integers(1, 5)):
            at(rng.uniform(10, duration_s - 10), "VIOLATION", f"OBJECT: {rng.choice(OBJECTS)}")

    # Room changes
    if rng.random() < p["room_change_prob"]:
        for _ in range(rng.integers(1, 4)):
            at(rng.uniform(60, duration_s - 30), "VIOLATION", f"ROOM: {rng.choice(ROOM_NOTES)}")

    # Multi-monitor (rare, mostly suspicious/cheating)
    if rng.random() < p.get("multi_monitor_prob", 0.0):
        at(rng.uniform(30, duration_s - 30), "VIOLATION", "Multi-Monitor: 2 screens")

    events.sort(key=lambda e: e["timestamp"])
    return events


def _generate_session(args, index):
    """Generates one complete session. Returns stats dict, or None if already done."""
    seed = args["seed"]
    sid = sid_for(seed, index)
    out_dir = os.path.join(args["out_root"], sid)
    from tools.synthetic_manifest import done_matches, lock_hash
    _lock_cfg = {"sid": sid, "code": "generate_synthetic_data"}
    if done_matches(out_dir, lock_hash(_lock_cfg)):
        return None

    rng = rng_for(seed, index)
    profile_name = _pick_profile(rng, args["profiles"])
    profile_cfg = PROFILES[profile_name]

    duration_s = float(rng.uniform(*DURATION_RANGES[profile_name]))
    fps = args["fps"]
    metrics_hz = args["metrics_hz"]
    metric_interval = max(1, int(round(fps / metrics_hz)))
    n_metrics = int(math.ceil(duration_s * fps / metric_interval))

    traj = HeadTrajectory(profile_name, fps=fps, seed=int(rng.integers(0, 2 ** 31)))
    st = traj.build(duration_s)
    sim = SessionSimulator(profile=profile_name, seed=int(rng.integers(0, 2 ** 31)), fps=fps)

    start_time = BASE_DATE + timedelta(days=int(index))
    events = [make_record(sid, start_time, "INFO", "Synthetic session started")]
    timers = _Timers()
    phone_prev = False

    audio_engine = args.get("audio_engine")
    audio_dir = os.path.join(out_dir, "audio") if audio_engine else None
    async_events = _async_events(sid, profile_cfg, duration_s, start_time, rng,
                                 audio_dir=audio_dir, audio_engine=audio_engine)

    # Align the VAD signal with real AUDIO events so metrics correlate with sound.
    if audio_dir:
        for e in async_events:
            if e["type"] == "AUDIO":
                t_sec = (datetime.fromisoformat(e["timestamp"]) - start_time).total_seconds()
                fi = int(round(t_sec * fps))
                lo, hi = max(0, fi - int(0.5 * fps)), min(st["n"] - 1, fi + int(3.0 * fps))
                st["vad"][lo:hi] = np.clip(st["vad"][lo:hi] + 0.6, 0, 1)

    yaw_th = sim.thresholds.rules("yaw_threshold_deg", default=35.0)
    pitch_th = sim.thresholds.rules("pitch_threshold_deg", default=30.0)
    look_thresh_f = sim.thresholds.rules("look_away_threshold_sec", default=0.5) * fps
    multi_thresh_f = sim.thresholds.rules("multiple_faces_threshold_sec", default=2.0) * fps
    face_missing_thresh_f = sim.thresholds.rules("face_missing_threshold_sec", default=5.0) * fps

    rich = bool(args["rich_sessions"] and index < args["rich_sessions"])
    os.makedirs(out_dir, exist_ok=True)
    image_stride = max(1, args.get("image_stride", 10))
    if rich:
        os.makedirs(os.path.join(out_dir, "images"), exist_ok=True)

    faces = None
    bg = None
    if rich and not args["use_blender"]:
        fc_dir = args.get("face_crops")
        crop_files = sorted(glob.glob(os.path.join(fc_dir, "*.jpg"))) if fc_dir and os.path.isdir(fc_dir) else []
        if crop_files:
            a = crop_files[int(rng.integers(0, len(crop_files)))]
            b = crop_files[int(rng.integers(0, len(crop_files)))]
            faces = [cv2.imread(a), cv2.imread(b)]
        bg = _build_background(sim.webcam.width, sim.webcam.height, seed=int(rng.integers(0, 2 ** 31)))

    for k in range(n_metrics):
        i = k * metric_interval
        frame_idx = min(i, st["n"] - 1)
        state = {
            "yaw": st["yaw"][frame_idx], "pitch": st["pitch"][frame_idx], "roll": st["roll"][frame_idx],
            "gaze_lr": st["gaze_lr"][frame_idx], "gaze_ud": st["gaze_ud"][frame_idx],
            "face_count": int(st["face_count"][frame_idx]), "vad": st["vad"][frame_idx], "lip": st["lip"][frame_idx],
        }

        ry, rp, _, gz, phone_visible = sim.raw_measure(
            state["yaw"], state["pitch"], state["roll"], state["gaze_lr"], state["gaze_ud"])
        y, p = sim.smooth(ry, rp)
        metric = sim.build_metric(y, p, ry, rp, gz, phone_visible, state)
        ts = start_time + timedelta(seconds=float(i) / fps)

        image_path = None
        if rich and k % image_stride == 0:
            image_path = _save_synthetic_frame(
                sim, state, out_dir, k, faces=faces, bg=bg,
                use_blender=bool(args["use_blender"]))
        metric_row = {k: v for k, v in metric.items() if k != "fused_reasons"}
        events.append(make_record(sid, ts, "METRICS", metric_row, image_path))

        # --- Pose-derived violations ---
        head_away = abs(y) > yaw_th or abs(p) > pitch_th
        gaze_away = bool(gz.get("direction", "CENTER") != "CENTER")
        away = head_away or gaze_away

        if away:
            if timers.look_away_start is None:
                timers.look_away_start = i
            elif (i - timers.look_away_start) >= look_thresh_f and (i - timers.last_look_away) >= 2 * fps:
                vtype = "HEAD_AWAY" if head_away else "GAZE_AWAY"
                msg = f"Looking Away ({vtype} | Y:{int(y)} P:{int(p)})"
                events.append(make_record(sid, ts, "VIOLATION", msg))
                timers.last_look_away = i
        else:
            timers.look_away_start = None

        # Phone head turn (side camera sees frontal face)
        if phone_visible and not phone_prev and (i - timers.last_phone_turn) >= 4 * fps:
            events.append(make_record(sid, ts, "VIOLATION", "ALERT: Head Turn Detected (Phone View)"))
            timers.last_phone_turn = i
        phone_prev = bool(phone_visible)

        # Face rules
        fc = int(state["face_count"])
        if fc > 1:
            if timers.multi_start is None:
                timers.multi_start = i
            elif (i - timers.multi_start) >= multi_thresh_f and (i - timers.last_multi_emit) >= 30 * fps:
                events.append(make_record(sid, ts, "VIOLATION", "Multiple Faces Detected"))
                timers.last_multi_emit = i
                timers.multi_start = None
        elif fc == 0:
            if timers.face_missing_start is None:
                timers.face_missing_start = i
            elif (i - timers.face_missing_start) >= face_missing_thresh_f and (i - timers.last_face_missing) >= 30 * fps:
                events.append(make_record(sid, ts, "VIOLATION", "Face Missing"))
                timers.last_face_missing = i
                timers.face_missing_start = None
        else:
            timers.multi_start = None
            timers.face_missing_start = None

        # Gaze triangulation toward phone
        if metric.get("looking_at_phone") and (i - timers.last_triangulation) >= 2 * fps:
            dist = metric.get("phone_distance_cm", -1.0)
            events.append(make_record(
                sid, ts, "VIOLATION",
                f"GAZE TRIANGULATION: looking at phone region (dist {dist}cm)"))
            timers.last_triangulation = i

        # Fusion warnings
        if metric.get("fused_status") != "SAFE" and (i - timers.last_fusion) >= 2 * fps:
            reasons = metric.get("fused_reasons") or []
            if reasons:
                status = metric["fused_status"]
                score = metric.get("fused_score", 0.0)
                events.append(make_record(
                    sid, ts, "VIOLATION",
                    f"FUSION [{status} {score:.2f}]: {reasons[0]}"))
                timers.last_fusion = i

    events.extend(async_events)
    events.sort(key=lambda e: e["timestamp"])

    n_violations = sum(1 for e in events if e["type"] == "VIOLATION")
    focus_count = sum(1 for e in events if isinstance(e.get("data"), str) and "Focus Lost" in e["data"])
    n_metrics_rows = sum(1 for e in events if e["type"] == "METRICS")

    confidence = int(rng.integers(profile_cfg["confidence"][0], profile_cfg["confidence"][1] + 1))
    write_session(out_dir, sid, events, start_time, duration_s,
                  profile_name, confidence, n_metrics_rows, n_violations, focus_count)

    return {
        "sid": sid, "profile": profile_name, "duration_s": round(duration_s, 1),
        "n_metrics": n_metrics_rows, "n_events": len(events), "n_violations": n_violations,
    }


def _build_background(width, height, seed):
    """Procedural dim office scene: wall gradient, desk, monitor glow, sensor noise, vignette."""
    rng = np.random.default_rng(seed)
    img = np.zeros((height, width, 3), dtype=np.uint8)
    grad = np.linspace(1.0, 0.0, height, dtype=np.float32)[:, None]
    for ch, (lo, hi) in enumerate(((22, 42), (20, 40), (26, 48))):  # B, G, R
        img[:, :, ch] = (lo + grad * (hi - lo)).astype(np.uint8)
    desk_y = int(height * 0.74)
    img[desk_y:, :] = (36, 29, 25)
    mw, mh = int(width * 0.52), int(height * 0.30)
    x0, y0 = (width - mw) // 2, int(height * 0.20)
    cv2.rectangle(img, (x0, y0), (x0 + mw, y0 + mh), (32, 38, 50), -1)
    cv2.rectangle(img, (x0 + 6, y0 + 6), (x0 + mw - 6, y0 + mh - 6), (52, 62, 82), 2)
    img = np.clip(img.astype(np.float32) + rng.normal(0, 2.5, (height, width, 3)), 0, 255)
    yy, xx = np.mgrid[0:height, 0:width]
    r = np.sqrt((xx - width / 2.0) ** 2 + (yy - height / 2.0) ** 2)
    r = np.clip(r / (0.72 * max(width, height)), 0.0, 1.0)
    img = img * (1.0 - 0.5 * r[..., None])
    return img.astype(np.uint8)


def _face_crop_mask(size):
    mask = np.zeros((size, size), dtype=np.uint8)
    cv2.ellipse(mask, (size // 2, size // 2), (int(size * 0.46), int(size * 0.52)),
                0, 0, 360, 255, -1)
    return cv2.GaussianBlur(mask, (0, 0), sigmaX=size / 12)


def _face_transform(pts2d, crop_size):
    """Affine that maps the crop's eyes/nose onto the projected landmark locations."""
    src = np.float32([
        [0.72 * crop_size, 0.40 * crop_size],  # subject's left eye  (mp 468 iris)
        [0.28 * crop_size, 0.40 * crop_size],  # subject's right eye (mp 473 iris)
        [0.50 * crop_size, 0.52 * crop_size],  # nose tip (mp 1)
    ])
    dst = np.float32([pts2d[468], pts2d[473], pts2d[1]])
    return cv2.getAffineTransform(src, dst)


def _warp_face(img, crop, M):
    h, w = img.shape[:2]
    mask = _face_crop_mask(crop.shape[0])
    warped = cv2.warpAffine(crop, M, (w, h), borderValue=0)
    m3 = (cv2.warpAffine(mask, M, (w, h)).astype(np.float32) / 255.0)[..., None]
    img[:] = (img.astype(np.float32) * (1.0 - m3) + warped.astype(np.float32) * m3).astype(np.uint8)


def _save_synthetic_frame(sim, state, out_dir, k, faces=None, bg=None, use_blender=False):
    """Renders a webcam frame. When use_blender is set the frame is a photoreal
    Blender render of the 3D head at the session's pose; otherwise it pastes a
    real LFW face (faces[0], plus a smaller second person when face_count > 1)
    at the pose-projected landmark locations. Returns the saved image path."""
    if use_blender:
        return _save_blender_frame(sim, state, out_dir, k)
    try:
        world3d, idxs, _ = sim._world_from_state(
            float(state["yaw"]), float(state["pitch"]), float(state["roll"]),
            float(state["gaze_lr"]), float(state["gaze_ud"]))
        pts = sim.webcam.project(world3d)
        pts2d = {idx: pts[n] for n, idx in enumerate(idxs)}
        img = bg.copy()
        if faces and faces[0] is not None:
            M = _face_transform(pts2d, faces[0].shape[0])
            _warp_face(img, faces[0], M)
            if int(state.get("face_count", 1)) > 1 and len(faces) > 1 and faces[1] is not None:
                h, w = img.shape[:2]
                small = cv2.resize(faces[1], (0, 0), fx=0.6, fy=0.6, interpolation=cv2.INTER_AREA)
                T = cv2.getRotationMatrix2D((w / 2.0, h * 0.45), 0.0, 0.55)
                T[0, 2] += -int(w * 0.34)
                T[1, 2] += int(h * 0.18)
                M2 = (T @ np.vstack([M, [0.0, 0.0, 1.0]]))[:2]
                _warp_face(img, small, M2)
                img[:] = cv2.GaussianBlur(img, (0, 0), 0.8)
        fname = f"{k:06d}.jpg"
        path = os.path.join(out_dir, "images", fname)
        cv2.imwrite(path, img)
        return os.path.join("images", fname)
    except Exception:
        return None


# Blender renderer instance cache, per worker process (bpy loads once).
_BLENDER = None
_BLENDER_FAILED = False


def _get_blender_renderer(width, height):
    """Lazily build (and cache) the shared BlenderRenderer for this process."""
    global _BLENDER, _BLENDER_FAILED
    if _BLENDER is not None:
        return _BLENDER
    if _BLENDER_FAILED:
        return None
    try:
        from tools.renderers.blender_renderer import BlenderRenderer
        _BLENDER = BlenderRenderer(width=width, height=height, engine="EEVEE", device="GPU")
        return _BLENDER
    except Exception as e:
        _BLENDER_FAILED = True
        print(f"[SYNTH] Blender renderer unavailable: {e}")
        return None


def _save_blender_frame(sim, state, out_dir, k):
    """Photoreal frame: renders the 3D head at the session's yaw/pitch/roll."""
    renderer = _get_blender_renderer(sim.webcam.width, sim.webcam.height)
    if renderer is None:
        return None
    try:
        visible = int(state.get("face_count", 1)) >= 1
        img = renderer.render(
            float(state["yaw"]), float(state["pitch"]), float(state["roll"]),
            sim.head_center, visible=visible)
        fname = f"{k:06d}.jpg"
        path = os.path.join(out_dir, "images", fname)
        cv2.imwrite(path, img)
        return os.path.join("images", fname)
    except Exception as e:
        print(f"[SYNTH] blender frame failed: {e}")
        return None


def write_session(out_dir, sid, events, start_time, duration_s,
                  profile_name, confidence, n_metrics, n_violations, focus_count):
    """Atomically writes events.jsonl + FINAL_REPORT.md, then the .done marker."""

    # Emoji-free report (no spurious visual markers in training labels).
    m = int(duration_s // 60)
    s = int(duration_s % 60)
    timeline = []
    for e in events[-40:]:
        if e["type"] == "VIOLATION" and isinstance(e.get("data"), str):
            hhmmss = datetime.fromisoformat(e["timestamp"]).strftime("%H:%M:%S")
            timeline.append(f"- **{hhmmss}**: {e['data']}")
    timeline_block = "\n".join(timeline) if timeline else "- No violations recorded"

    report = f"""# Final Proctoring Report
**Session Date:** {start_time.strftime('%Y-%m-%d %H:%M')}
**Verdict:** **{profile_name}** (Confidence: {confidence}/100)

## AI Analysis (Isolation Forest Model)
Synthetic session generated by the geometry-driven world simulator.

## Statistics
- **Duration:** {m} min {s} sec
- **ML Anomalies Detected:** 0
- **Focus Lost Events:** {focus_count}
- **Hard Rule Violations:** {n_violations}

## Forensic Timeline
{timeline_block}

---
*Generated by Synthetic Data Engine*
"""

    events_tmp = os.path.join(out_dir, "events.jsonl.tmp")
    report_tmp = os.path.join(out_dir, "FINAL_REPORT.md.tmp")
    with open(events_tmp, "w", encoding="utf-8") as f:
        for rec in events:
            f.write(json.dumps(rec) + "\n")
    with open(report_tmp, "w", encoding="utf-8") as f:
        f.write(report)
    os.replace(events_tmp, os.path.join(out_dir, "events.jsonl"))
    os.replace(report_tmp, os.path.join(out_dir, "FINAL_REPORT.md"))
    try:
        from tools.synthetic_manifest import lock_hash, write_done, write_scenario_manifest
        cfg = {"sid": sid, "code": "generate_synthetic_data"}
        write_scenario_manifest(
            out_dir,
            seeds={"session": hash(sid) & 0xFFFFFFFF},
            domains={"profile": profile_name},
            observable_truth={"violations": n_violations, "focus": focus_count},
            pair_id=None,
            config=cfg,
        )
        write_done(out_dir, lock_hash(cfg))
    except Exception:
        with open(os.path.join(out_dir, ".done"), "w", encoding="utf-8") as f:
            f.write("ok")


def _write_state(out_root, state):
    with open(os.path.join(out_root, ".state.json"), "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def _parse_ratio(spec):
    parts = [x.strip() for x in spec.replace(":", ",").split(",")]
    if len(parts) != 3:
        raise SystemExit("--ratio must be CLEAN:SUSPICIOUS:CHEATING, e.g. 60:25:15")
    names = ["CLEAN", "SUSPICIOUS", "CHEATING"]
    weights = [int(p) for p in parts]
    total = sum(weights)
    return [{"name": n, "weight": w / total} for n, w in zip(names, weights)]


def main():
    ap = argparse.ArgumentParser(description="Resumable synthetic proctoring data generator")
    ap.add_argument("--total-events", type=int, default=12_000_000,
                    help="target number of METRICS rows (default 12,000,000)")
    ap.add_argument("--ratio", default="60:25:15", help="CLEAN:SUSPICIOUS:CHEATING")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="data/synthetic")
    ap.add_argument("--metrics-hz", type=float, default=2.0)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--max-sessions", type=int, default=0, help="hard cap (0 = auto)")
    ap.add_argument("--rich-sessions", type=int, default=0,
                    help="number of sessions that also save synthetic webcam frames")
    ap.add_argument("--renderer", choices=["warp", "blender"], default="warp",
                    help="how rich-session webcam frames are produced (warp=paste face crop, blender=3D render)")
    ap.add_argument("--audio-engine", choices=["none", "edge-tts", "pyttsx3"], default="none",
                    help="TTS engine for synthetic AUDIO clips (edge-tts needs internet)")
    ap.add_argument("--face-crops", default=None, help="(reserved) LFW face crop dir")
    ap.add_argument("--image-stride", type=int, default=10)
    ap.add_argument("--smoke", action="store_true", help="tiny run to validate the pipeline")
    args = ap.parse_args()

    if args.smoke:
        args.total_events = 4000
        args.workers = max(1, min(args.workers, 2))

    profiles = _parse_ratio(args.ratio)
    avg_duration = sum(p["weight"] * (
        (DURATION_RANGES[p["name"]][0] + DURATION_RANGES[p["name"]][1]) / 2.0) for p in profiles)
    rows_per_session = args.metrics_hz * avg_duration
    n_sessions = max(2, int(math.ceil(args.total_events / rows_per_session * 1.1)))
    if args.max_sessions:
        n_sessions = min(n_sessions, args.max_sessions)

    out_root = os.path.abspath(args.out)
    os.makedirs(out_root, exist_ok=True)

    args_dict = {
        "seed": args.seed, "out_root": out_root, "fps": args.fps,
        "metrics_hz": args.metrics_hz, "profiles": profiles,
        "rich_sessions": args.rich_sessions, "face_crops": args.face_crops,
        "image_stride": args.image_stride,
        "use_blender": args.renderer == "blender",
        "audio_engine": args.audio_engine if args.audio_engine != "none" else None,
    }

    # Resume: skip completed sessions.
    todo = []
    for idx in range(n_sessions):
        if not os.path.isfile(os.path.join(out_root, sid_for(args.seed, idx), ".done")):
            todo.append(idx)

    print(f"[SYNTH] target={args.total_events} rows, ratio={args.ratio}, sessions={n_sessions}, "
          f"already done={n_sessions - len(todo)}, workers={args.workers}, seed={args.seed}")
    print(f"[SYNTH] output: {out_root}")

    t0 = time.time()
    stats = {}
    done = 0
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(_generate_session, args_dict, i): i for i in todo}
        for fut in as_completed(futures):
            idx = futures[fut]
            try:
                res = fut.result()
            except Exception as e:
                print(f"[SYNTH] session {idx} FAILED: {e}")
                continue
            if res:
                stats[idx] = res
                done += 1
                if done % 25 == 0:
                    _write_state(out_root, {"seed": args.seed, "sessions_total": n_sessions,
                                            "sessions_done": done, "in_progress": True})
                    print(f"[SYNTH] {done}/{len(todo)} sessions done "
                          f"({sum(s['n_metrics'] for s in stats.values())} metric rows, "
                          f"{time.time() - t0:.0f}s elapsed)")

    total_rows = sum(s["n_metrics"] for s in stats.values())
    elapsed = time.time() - t0
    _write_state(out_root, {
        "seed": args.seed, "sessions_total": n_sessions, "sessions_done": done,
        "generated_metric_rows": total_rows, "elapsed_s": round(elapsed, 1), "in_progress": False,
    })

    from collections import Counter
    counts = Counter(s["profile"] for s in stats.values())
    print(f"\n[SYNTH] DONE in {elapsed:.0f}s ({elapsed / max(done, 1):.2f}s/session)")
    print(f"[SYNTH] sessions={done}, metric_rows={total_rows}, events="
          f"{sum(s['n_events'] for s in stats.values())}")
    print(f"[SYNTH] profiles={dict(counts)}")


if __name__ == "__main__":
    main()
