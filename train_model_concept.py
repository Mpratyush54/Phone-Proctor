"""
=============================================================================
  MULTI-MODAL CHEATING DETECTION - UNSUPERVISED LEARNING PIPELINE
=============================================================================
  This script demonstrates the complete ML pipeline for training a cheating
  detection model using UNSUPERVISED LEARNING on multi-modal proctoring data.

  Data Sources:
    1. Event Logs   (JSONL)  - Focus loss, gaze violations, head movement
    2. Vision Data  (JPG)    - Webcam snapshots analyzed via MediaPipe FaceMesh
    3. Audio Data   (WAV)    - Microphone recordings analyzed for speech/noise

  Unsupervised Models:
    - Isolation Forest       - Ensemble anomaly detector
    - Statistical Z-Score    - Baseline deviation detector

  Author: Pratyush Mishra   
=============================================================================
"""

import os
import sys
import json
import re
import time
import warnings
import numpy as np
from datetime import datetime, timedelta
from collections import defaultdict, Counter

warnings.filterwarnings('ignore')

# ============================================================================
#   CONFIGURATION
# ============================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIRS = [
    os.path.join(BASE_DIR, 'data', 'dataset'),
    os.path.join(BASE_DIR, 'data', 'dataset.old'),
    os.path.join(BASE_DIR, 'data', 'synthetic'),
]
AUDIO_DIR = os.path.join(BASE_DIR, 'data', 'audio')
MODEL_SAVE_PATH = os.path.join(BASE_DIR, 'models', 'cheat_model_unsupervised.pkl')


def print_header(step_num, title):
    """Print a formatted step header."""
    print()
    print("=" * 70)
    print(f"  STEP {step_num}: {title}")
    print("=" * 70)


def print_sub(text):
    """Print indented sub-step text."""
    print(f"    {text}")


def print_table(headers, rows, col_widths=None):
    """Print a formatted table."""
    if col_widths is None:
        col_widths = [max(len(str(h)), max((len(str(r[i])) for r in rows), default=5)) + 2
                      for i, h in enumerate(headers)]
    
    header_line = "  | " + " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers)) + " |"
    sep_line = "  +" + "+".join("-" * (w + 2) for w in col_widths) + "+"
    
    print(sep_line)
    print(header_line)
    print(sep_line)
    for row in rows:
        line = "  | " + " | ".join(str(row[i]).ljust(col_widths[i]) for i in range(len(headers))) + " |"
        print(line)
    print(sep_line)


# ============================================================================
#  STEP 1: DATA LOADING
# ============================================================================
def step1_load_data():
    print_header(1, "DATA LOADING")
    print()
    print("    Loading raw session data from disk...")
    print(f"    Data directories: {DATA_DIRS}")
    print()

    sessions = []

    for data_dir in DATA_DIRS:
        if not os.path.exists(data_dir):
            print(f"    [SKIP] Directory not found: {data_dir}")
            continue

        dir_name = os.path.basename(data_dir)
        session_ids = [s for s in os.listdir(data_dir)
                       if os.path.isdir(os.path.join(data_dir, s))]
        print(f"    Found {len(session_ids)} sessions in '{dir_name}/'")

        for sid in session_ids:
            session_path = os.path.join(data_dir, sid)
            events_file = os.path.join(session_path, 'events.jsonl')
            report_file = os.path.join(session_path, 'FINAL_REPORT.md')

            if not os.path.isfile(events_file):
                continue

            # Load events
            raw_events = []
            with open(events_file, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        evt = json.loads(line)
                        raw_events.append(evt)
                    except json.JSONDecodeError:
                        pass

            # Load report verdict (for evaluation only, NOT for training)
            verdict = 'UNKNOWN'
            confidence = 0
            if os.path.isfile(report_file):
                with open(report_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    if 'CLEAN' in content:
                        verdict = 'CLEAN'
                    elif 'SUSPICIOUS' in content:
                        verdict = 'SUSPICIOUS'
                    elif 'CHEATING' in content:
                        verdict = 'CHEATING'
                    m = re.search(r'Confidence:\s*\**\s*(\d+)/100', content)
                    if m:
                        confidence = int(m.group(1))

            # Collect image paths
            image_paths = []
            for evt in raw_events:
                ip = evt.get('image_path')
                if ip:
                    image_paths.append(ip)

            sessions.append({
                'session_id': sid,
                'raw_events': raw_events,
                'verdict': verdict,
                'confidence': confidence,
                'path': session_path,
                'image_paths': image_paths,
            })

    # Summary
    total_events = sum(len(s['raw_events']) for s in sessions)
    total_images = sum(len(s['image_paths']) for s in sessions)

    # Count audio files
    audio_files = []
    if os.path.isdir(AUDIO_DIR):
        audio_files = [f for f in os.listdir(AUDIO_DIR) if f.endswith('.wav')]

    print()
    print("    --- Raw Data Summary ---")
    print_table(
        ["Metric", "Count"],
        [
            ["Total Sessions", len(sessions)],
            ["Total Events (raw)", total_events],
            ["Total Images (JPG)", total_images],
            ["Total Audio Clips (WAV)", len(audio_files)],
        ]
    )

    # Verdict distribution (for later evaluation)
    verdict_counts = Counter(s['verdict'] for s in sessions)
    print()
    print("    Verdict Distribution (from FINAL_REPORT, used for evaluation only):")
    print_table(
        ["Verdict", "Count"],
        [[v, c] for v, c in sorted(verdict_counts.items())]
    )

    return sessions, audio_files


# ============================================================================
#  STEP 2: DATA CLEANING
# ============================================================================
def step2_clean_data(sessions):
    print_header(2, "DATA CLEANING")
    print()

    total_before = sum(len(s['raw_events']) for s in sessions)
    sessions_before = len(sessions)
    
    cleaned_sessions = []
    cleaning_stats = {
        'empty_data': 0,
        'invalid_json': 0,
        'missing_timestamp': 0,
        'duplicate_events': 0,
        'short_sessions': 0,
    }

    for sess in sessions:
        clean_events = []
        seen_keys = set()  # for deduplication

        for evt in sess['raw_events']:
            # Check 1: Must have timestamp
            ts_str = evt.get('timestamp')
            if not ts_str:
                cleaning_stats['missing_timestamp'] += 1
                continue

            # Check 2: Parse timestamp
            try:
                ts = datetime.fromisoformat(ts_str)
            except (ValueError, TypeError):
                cleaning_stats['missing_timestamp'] += 1
                continue

            # Check 3: Must have data field
            data = evt.get('data', '')
            if not data:
                cleaning_stats['empty_data'] += 1
                continue

            # Check 4: Normalize data field - convert dict to string
            if isinstance(data, dict):
                data = json.dumps(data)

            # Check 5: Deduplication (same timestamp + same data = duplicate)
            dedup_key = f"{ts_str}|{data[:50]}"
            if dedup_key in seen_keys:
                cleaning_stats['duplicate_events'] += 1
                continue
            seen_keys.add(dedup_key)

            clean_events.append({
                'timestamp': ts_str,
                '_ts': ts,
                'type': evt.get('type', 'UNKNOWN'),
                'data': data,
                'image_path': evt.get('image_path'),
            })

        # Check 6: Skip very short sessions (less than 3 events)
        if len(clean_events) < 3:
            cleaning_stats['short_sessions'] += 1
            continue

        # Sort by timestamp
        clean_events.sort(key=lambda e: e['_ts'])

        sess_copy = dict(sess)
        sess_copy['events'] = clean_events
        sess_copy['duration_sec'] = (clean_events[-1]['_ts'] - clean_events[0]['_ts']).total_seconds()
        cleaned_sessions.append(sess_copy)

    total_after = sum(len(s['events']) for s in cleaned_sessions)

    print("    --- Cleaning Steps Applied ---")
    print()
    print("    1. Remove events without timestamps")
    print("    2. Parse and validate ISO timestamps")
    print("    3. Remove events with empty/null data fields")
    print("    4. Normalize dict-type data fields to strings")
    print("    5. Deduplicate events (same timestamp + data)")
    print("    6. Drop sessions with fewer than 3 events")
    print()

    print("    --- Cleaning Statistics ---")
    print_table(
        ["Cleaning Rule", "Removed"],
        [
            ["Missing/invalid timestamp", cleaning_stats['missing_timestamp']],
            ["Empty data field", cleaning_stats['empty_data']],
            ["Duplicate events", cleaning_stats['duplicate_events']],
            ["Short sessions (<3 events)", cleaning_stats['short_sessions']],
        ]
    )

    print()
    print("    --- Before vs After ---")
    print_table(
        ["Metric", "Before", "After", "Removed"],
        [
            ["Sessions", sessions_before, len(cleaned_sessions),
             sessions_before - len(cleaned_sessions)],
            ["Events", total_before, total_after,
             total_before - total_after],
        ]
    )

    # Show a sample cleaned event
    if cleaned_sessions:
        sample = cleaned_sessions[0]['events'][0]
        print()
        print("    --- Sample Cleaned Event ---")
        print(f"    Timestamp : {sample['timestamp']}")
        print(f"    Type      : {sample['type']}")
        print(f"    Data      : {sample['data'][:80]}...")
        print(f"    Image     : {sample['image_path']}")

    return cleaned_sessions


# ============================================================================
#  STEP 3: EVENT LOG FEATURE EXTRACTION
# ============================================================================
def classify_event(data_str):
    """Classify an event data string into a category."""
    if not isinstance(data_str, str):
        data_str = str(data_str)
    d = data_str.upper()
    if 'FOCUS LOST' in d:
        return 'focus_lost'
    elif 'GAZE' in d or 'LOOKING AWAY' in d:
        return 'gaze_away'
    elif 'HEAD' in d:
        return 'head_away'
    elif any(x in d for x in ['OBJECT', 'LAPTOP', 'PHONE', 'BOOK']):
        return 'object_detected'
    elif any(x in d for x in ['FACE', 'NO FACE', 'MULTIPLE']):
        return 'face_anomaly'
    elif 'AUDIO' in d:
        return 'audio'
    else:
        return 'other'


def extract_yaw_pitch(data_str):
    """Extract yaw/pitch angles from event data string."""
    if not isinstance(data_str, str):
        data_str = str(data_str)
    yaw_m = re.search(r'Y:(-?\d+)', data_str)
    pitch_m = re.search(r'P:(-?\d+)', data_str)
    yaw = int(yaw_m.group(1)) if yaw_m else None
    pitch = int(pitch_m.group(1)) if pitch_m else None
    return yaw, pitch


def step3_extract_event_features(sessions):
    print_header(3, "EVENT LOG FEATURE EXTRACTION")
    print()
    print("    Extracting behavioral features from event logs...")
    print()
    print("    Features being extracted:")
    print("      - Violation rates per minute (gaze, focus, head)")
    print("      - Violation proportions (ratio of each type)")
    print("      - Head pose statistics (yaw/pitch mean, max, std)")
    print("      - Burst density (rapid-fire violations < 3 sec apart)")
    print("      - Session duration")
    print("      - Violation diversity (number of distinct types)")
    print("      - Suspicious app focus switches")
    print()

    all_features = []
    event_type_totals = Counter()

    for sess in sessions:
        events = sess['events']
        duration_sec = max(sess.get('duration_sec', 1), 1)
        duration_min = max(duration_sec / 60, 0.01)
        n_events = len(events)

        # Categorize events
        categories = Counter()
        yaws, pitches = [], []

        for evt in events:
            data = evt['data']
            cat = classify_event(data)
            categories[cat] += 1
            event_type_totals[cat] += 1

            yaw, pitch = extract_yaw_pitch(data)
            if yaw is not None:
                yaws.append(abs(yaw))
            if pitch is not None:
                pitches.append(abs(pitch))

        # Burst density
        timestamps = [e['_ts'] for e in events]
        burst_count = 0
        for i in range(1, len(timestamps)):
            if (timestamps[i] - timestamps[i - 1]).total_seconds() < 3.0:
                burst_count += 1

        # Suspicious app focus
        suspicious_focus = 0
        for evt in events:
            data = evt['data']
            if not isinstance(data, str):
                continue
            if 'Focus Lost' in data:
                dl = data.lower()
                if any(x in dl for x in ['chrome', 'edge', 'firefox', 'whatsapp',
                                          'telegram', 'discord', 'slack']):
                    suspicious_focus += 1

        features = {
            # Rate features (events per minute)
            'gaze_rate': categories['gaze_away'] / duration_min,
            'focus_rate': categories['focus_lost'] / duration_min,
            'head_rate': categories['head_away'] / duration_min,
            'total_violations_per_min': n_events / duration_min,

            # Proportion features
            'gaze_ratio': categories['gaze_away'] / max(n_events, 1),
            'focus_ratio': categories['focus_lost'] / max(n_events, 1),
            'head_ratio': categories['head_away'] / max(n_events, 1),

            # Count features
            'object_count': categories['object_detected'],
            'face_anomaly_count': categories['face_anomaly'],
            'audio_count': categories['audio'],

            # Head pose statistics
            'yaw_mean': float(np.mean(yaws)) if yaws else 0,
            'yaw_max': float(np.max(yaws)) if yaws else 0,
            'yaw_std': float(np.std(yaws)) if yaws else 0,
            'pitch_mean': float(np.mean(pitches)) if pitches else 0,
            'pitch_max': float(np.max(pitches)) if pitches else 0,
            'pitch_std': float(np.std(pitches)) if pitches else 0,

            # Temporal features
            'burst_density': burst_count / max(n_events, 1),
            'session_duration_min': duration_min,
            'violation_diversity': len([v for v in categories.values() if v > 0]),

            # App detection
            'suspicious_app_focus': suspicious_focus,
        }

        all_features.append(features)

    # Show event type distribution
    print("    --- Event Type Distribution Across All Sessions ---")
    print_table(
        ["Event Category", "Total Count", "Percentage"],
        [
            [cat, count, f"{count / sum(event_type_totals.values()) * 100:.1f}%"]
            for cat, count in event_type_totals.most_common()
        ]
    )

    # Show feature summary
    print()
    print(f"    Extracted {len(all_features[0])} event-log features per session")
    print(f"    Total sessions processed: {len(all_features)}")

    # Show sample feature vector
    if all_features:
        print()
        print("    --- Sample Feature Vector (Session 0) ---")
        for k, v in list(all_features[0].items())[:10]:
            print(f"      {k:30s} = {v:.4f}")
        print(f"      ... ({len(all_features[0]) - 10} more features)")

    return all_features


# ============================================================================
#  STEP 4: VISION FEATURE EXTRACTION (MediaPipe FaceMesh)
# ============================================================================
def step4_extract_vision_features(sessions):
    print_header(4, "VISION FEATURE EXTRACTION (MediaPipe FaceMesh)")
    print()

    VISION_KEYS = [
        'v_no_face_ratio', 'v_multi_face_ratio', 'v_avg_face_count',
        'v_yaw_mean', 'v_yaw_max', 'v_yaw_std',
        'v_pitch_mean', 'v_pitch_max', 'v_pitch_std',
        'v_ear_mean', 'v_ear_min', 'v_ear_std',
        'v_face_size_mean', 'v_face_size_std',
        'v_brightness_mean', 'v_brightness_std',
        'v_images_analyzed',
    ]

    try:
        import cv2
        import mediapipe as mp_lib
        print("    [OK] OpenCV loaded:", cv2.__version__)
        print("    [OK] MediaPipe loaded:", mp_lib.__version__)
    except ImportError as e:
        print(f"    [WARN] Missing library: {e}")
        print("    Skipping vision features - filling with zeros")
        return [{k: 0 for k in VISION_KEYS} for _ in sessions]

    print()
    print("    Pipeline:")
    print("      1. Read each violation image (JPG, 640x480)")
    print("      2. Run MediaPipe FaceMesh (468 landmarks per face)")
    print("      3. Extract head pose via solvePnP (yaw, pitch)")
    print("      4. Compute Eye Aspect Ratio (EAR) for gaze")
    print("      5. Measure face bounding box size + image brightness")
    print("      6. Aggregate statistics across all images per session")
    print()

    # Initialize MediaPipe FaceMesh
    face_mesh = mp_lib.solutions.face_mesh.FaceMesh(
        static_image_mode=True,
        max_num_faces=3,
        refine_landmarks=True,
        min_detection_confidence=0.4,
    )

    # Eye landmark indices for EAR calculation
    L_EYE = [362, 385, 387, 263, 373, 380]
    R_EYE = [33, 160, 158, 133, 153, 144]

    def eye_aspect_ratio(landmarks, indices, w, h):
        pts = np.array([(landmarks[i].x * w, landmarks[i].y * h) for i in indices])
        v1 = np.linalg.norm(pts[1] - pts[5])
        v2 = np.linalg.norm(pts[2] - pts[4])
        hz = np.linalg.norm(pts[0] - pts[3])
        return (v1 + v2) / (2.0 * hz + 1e-6)

    def head_pose(landmarks, w, h):
        pts_2d = np.array([
            (landmarks[1].x * w,   landmarks[1].y * h),
            (landmarks[152].x * w, landmarks[152].y * h),
            (landmarks[33].x * w,  landmarks[33].y * h),
            (landmarks[263].x * w, landmarks[263].y * h),
            (landmarks[61].x * w,  landmarks[61].y * h),
            (landmarks[291].x * w, landmarks[291].y * h),
        ], dtype=np.float64)
        pts_3d = np.array([
            (0.0, 0.0, 0.0), (0.0, -63.6, -12.5),
            (-43.3, 32.7, -26.0), (43.3, 32.7, -26.0),
            (-28.9, -28.9, -24.1), (28.9, -28.9, -24.1),
        ], dtype=np.float64)
        cam = np.array([[w, 0, w/2], [0, w, h/2], [0, 0, 1]], dtype=np.float64)
        ok, rvec, _ = cv2.solvePnP(pts_3d, pts_2d, cam, np.zeros((4, 1)))
        if not ok:
            return 0.0, 0.0
        rmat, _ = cv2.Rodrigues(rvec)
        angles, _, _, _, _, _ = cv2.RQDecomp3x3(rmat)
        return float(angles[1]), float(angles[0])

    all_vision_features = []
    total_images_processed = 0
    total_faces_found = 0
    total_no_face = 0

    for idx, sess in enumerate(sessions):
        image_paths = sess.get('image_paths', [])

        if not image_paths:
            all_vision_features.append({k: 0 for k in VISION_KEYS})
            continue

        # Sample max 80 images per session for speed
        sample = image_paths if len(image_paths) <= 80 else [
            image_paths[i] for i in np.linspace(0, len(image_paths) - 1, 80, dtype=int)
        ]

        face_counts, yaws_v, pitches_v = [], [], []
        ears, face_sizes, brightnesses = [], [], []
        no_face, multi_face = 0, 0

        for img_rel in sample:
            full_path = os.path.join(sess['path'], img_rel)
            if not os.path.isfile(full_path):
                continue

            img = cv2.imread(full_path)
            if img is None:
                continue

            h, w = img.shape[:2]
            total_images_processed += 1

            # Brightness
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            brightnesses.append(float(np.mean(gray)) / 255.0)

            # Face detection
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            results = face_mesh.process(rgb)

            if not results.multi_face_landmarks:
                face_counts.append(0)
                no_face += 1
                total_no_face += 1
                continue

            n_faces = len(results.multi_face_landmarks)
            face_counts.append(n_faces)
            total_faces_found += n_faces
            if n_faces >= 2:
                multi_face += 1

            lm = results.multi_face_landmarks[0].landmark

            # Head pose
            yaw, pitch = head_pose(lm, w, h)
            yaws_v.append(abs(yaw))
            pitches_v.append(abs(pitch))

            # Eye aspect ratio
            l_ear = eye_aspect_ratio(lm, L_EYE, w, h)
            r_ear = eye_aspect_ratio(lm, R_EYE, w, h)
            ears.append((l_ear + r_ear) / 2.0)

            # Face size
            xs = [l.x for l in lm]
            ys = [l.y for l in lm]
            face_sizes.append((max(xs) - min(xs)) * (max(ys) - min(ys)))

        n = max(len(sample), 1)
        feats = {
            'v_no_face_ratio': no_face / n,
            'v_multi_face_ratio': multi_face / n,
            'v_avg_face_count': float(np.mean(face_counts)) if face_counts else 0,
            'v_yaw_mean': float(np.mean(yaws_v)) if yaws_v else 0,
            'v_yaw_max': float(np.max(yaws_v)) if yaws_v else 0,
            'v_yaw_std': float(np.std(yaws_v)) if yaws_v else 0,
            'v_pitch_mean': float(np.mean(pitches_v)) if pitches_v else 0,
            'v_pitch_max': float(np.max(pitches_v)) if pitches_v else 0,
            'v_pitch_std': float(np.std(pitches_v)) if pitches_v else 0,
            'v_ear_mean': float(np.mean(ears)) if ears else 0.3,
            'v_ear_min': float(np.min(ears)) if ears else 0.3,
            'v_ear_std': float(np.std(ears)) if ears else 0,
            'v_face_size_mean': float(np.mean(face_sizes)) if face_sizes else 0,
            'v_face_size_std': float(np.std(face_sizes)) if face_sizes else 0,
            'v_brightness_mean': float(np.mean(brightnesses)) if brightnesses else 0.5,
            'v_brightness_std': float(np.std(brightnesses)) if brightnesses else 0,
            'v_images_analyzed': len(sample),
        }
        all_vision_features.append(feats)

        if (idx + 1) % 20 == 0:
            print(f"    Processing... {idx + 1}/{len(sessions)} sessions")

    print()
    print("    --- Vision Processing Summary ---")
    print_table(
        ["Metric", "Value"],
        [
            ["Images processed", total_images_processed],
            ["Faces detected", total_faces_found],
            ["No-face frames", total_no_face],
            ["Vision features per session", len(VISION_KEYS)],
        ]
    )

    # Sample vision features
    for feat_list in all_vision_features:
        if feat_list.get('v_images_analyzed', 0) > 0:
            print()
            print("    --- Sample Vision Features ---")
            for k, v in feat_list.items():
                print(f"      {k:30s} = {v:.4f}")
            break

    face_mesh.close()
    return all_vision_features


# ============================================================================
#  STEP 5: AUDIO FEATURE EXTRACTION (scipy)
# ============================================================================
def step5_extract_audio_features(audio_files):
    print_header(5, "AUDIO FEATURE EXTRACTION")
    print()

    AUDIO_KEYS = ['a_rms_mean', 'a_rms_max', 'a_rms_std',
                  'a_zcr_mean', 'a_peak_mean', 'a_total_duration',
                  'a_speech_ratio', 'a_clip_count']

    if not audio_files:
        print("    [WARN] No audio files found.")
        print("    Audio features will be zero-filled.")
        return {k: 0 for k in AUDIO_KEYS}

    try:
        from scipy.io import wavfile as scipy_wav
        print(f"    [OK] scipy loaded")
    except ImportError:
        print("    [WARN] scipy not available. Skipping audio.")
        return {k: 0 for k in AUDIO_KEYS}

    print(f"    Found {len(audio_files)} WAV clips in {AUDIO_DIR}")
    print()
    print("    Pipeline:")
    print("      1. Read each WAV file (16kHz, mono)")
    print("      2. Normalize amplitude to float [-1, 1]")
    print("      3. Compute RMS energy (volume level)")
    print("      4. Compute Zero-Crossing Rate (noise vs speech)")
    print("      5. Compute peak amplitude")
    print("      6. Simple Voice Activity Detection (RMS > 0.02)")
    print("      7. Aggregate statistics across all clips")
    print()

    all_rms, all_zcr, all_peak, all_dur = [], [], [], []
    speech_seg = 0
    errors = 0

    for wf in audio_files:
        try:
            sr, data = scipy_wav.read(os.path.join(AUDIO_DIR, wf))
            if data.dtype != np.float32:
                data = data.astype(np.float32) / max(np.iinfo(data.dtype).max, 1)
            if len(data) == 0:
                continue

            rms = float(np.sqrt(np.mean(data ** 2)))
            peak = float(np.max(np.abs(data)))
            zcr = float(np.sum(np.abs(np.diff(np.sign(data)))) / (2 * len(data)))
            dur = len(data) / sr

            all_rms.append(rms)
            all_peak.append(peak)
            all_zcr.append(zcr)
            all_dur.append(dur)

            if rms > 0.02:
                speech_seg += 1
        except Exception:
            errors += 1

    feats = {
        'a_rms_mean': float(np.mean(all_rms)) if all_rms else 0,
        'a_rms_max': float(np.max(all_rms)) if all_rms else 0,
        'a_rms_std': float(np.std(all_rms)) if all_rms else 0,
        'a_zcr_mean': float(np.mean(all_zcr)) if all_zcr else 0,
        'a_peak_mean': float(np.mean(all_peak)) if all_peak else 0,
        'a_total_duration': float(np.sum(all_dur)) if all_dur else 0,
        'a_speech_ratio': speech_seg / max(len(audio_files), 1),
        'a_clip_count': len(audio_files),
    }

    print("    --- Audio Processing Summary ---")
    print_table(
        ["Metric", "Value"],
        [
            ["Clips processed", len(all_rms)],
            ["Processing errors", errors],
            ["Total audio duration", f"{sum(all_dur):.1f} sec"],
            ["Speech segments detected", f"{speech_seg}/{len(audio_files)}"],
            ["Mean RMS energy", f"{feats['a_rms_mean']:.4f}"],
            ["Mean Zero-Crossing Rate", f"{feats['a_zcr_mean']:.4f}"],
            ["Speech ratio", f"{feats['a_speech_ratio']:.2%}"],
        ]
    )

    return feats


# ============================================================================
#  STEP 6: FEATURE FUSION
# ============================================================================
def step6_fuse_features(event_features, vision_features, audio_features, sessions):
    print_header(6, "MULTI-MODAL FEATURE FUSION")
    print()
    print("    Combining features from all 3 modalities into a single matrix...")
    print()

    fused = []
    for i in range(len(sessions)):
        combined = {}
        combined.update(event_features[i])
        combined.update(vision_features[i])
        combined.update(audio_features)  # shared across sessions
        fused.append(combined)

    feature_names = sorted(fused[0].keys())
    X = np.array([[f[k] for k in feature_names] for f in fused])

    # Feature origin breakdown
    event_feats = [f for f in feature_names if not f.startswith('v_') and not f.startswith('a_')]
    vision_feats = [f for f in feature_names if f.startswith('v_')]
    audio_feats = [f for f in feature_names if f.startswith('a_')]

    print("    --- Feature Fusion Summary ---")
    print_table(
        ["Modality", "Features", "Examples"],
        [
            ["Event Logs", len(event_feats), ", ".join(event_feats[:3]) + "..."],
            ["Vision (CV)", len(vision_feats), ", ".join(vision_feats[:3]) + "..."],
            ["Audio", len(audio_feats), ", ".join(audio_feats[:3]) + "..."],
            ["TOTAL", len(feature_names), ""],
        ]
    )

    print()
    print(f"    Feature Matrix Shape: {X.shape}  ({X.shape[0]} sessions x {X.shape[1]} features)")

    # Check for NaN/Inf
    nan_count = np.isnan(X).sum()
    inf_count = np.isinf(X).sum()
    print(f"    NaN values: {nan_count},  Inf values: {inf_count}")
    if nan_count > 0 or inf_count > 0:
        print("    Replacing NaN/Inf with 0...")
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

    return X, feature_names


# ============================================================================
#  STEP 7: UNSUPERVISED MODEL TRAINING (Isolation Forest)
# ============================================================================
def step7_train_model(X, feature_names, sessions):
    print_header(7, "UNSUPERVISED MODEL TRAINING")
    print()
    print("    Algorithm: Isolation Forest (Ensemble Anomaly Detection)")
    print()
    print("    How it works:")
    print("      - Builds an ensemble of 200 random decision trees")
    print("      - Each tree randomly partitions the data by selecting")
    print("        random features and random split thresholds")
    print("      - Anomalous points are ISOLATED faster (fewer splits)")
    print("        because they are far from the majority of data")
    print("      - Anomaly Score = average path length across all trees")
    print("      - No labels needed! (Unsupervised Learning)")
    print()
    print("    Key: This model learns what 'NORMAL' behavior looks like")
    print("    and flags anything that deviates as potentially suspicious.")
    print()

    from sklearn.ensemble import IsolationForest
    from sklearn.preprocessing import StandardScaler

    # Step 7a: Standardize features
    print("    [7a] Standardizing features (zero mean, unit variance)...")
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    print(f"         Before scaling - Mean: {X.mean():.2f}, Std: {X.std():.2f}")
    print(f"         After scaling  - Mean: {X_scaled.mean():.4f}, Std: {X_scaled.std():.4f}")
    print()

    # Step 7b: Train Isolation Forest
    print("    [7b] Training Isolation Forest...")
    print("         n_estimators     = 200  (number of trees)")
    print("         contamination    = 0.15 (expected anomaly ratio)")
    print("         max_features     = 0.8  (feature sampling per tree)")
    print("         random_state     = 42   (reproducibility)")
    print()

    model = IsolationForest(
        n_estimators=200,
        contamination=0.15,
        max_features=0.8,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_scaled)
    print("         Training complete!")
    print()

    # Step 7c: Get anomaly scores
    print("    [7c] Computing anomaly scores...")
    raw_scores = model.decision_function(X_scaled)  # higher = more normal
    predictions = model.predict(X_scaled)            # 1 = normal, -1 = anomaly

    # Convert to cheat probability (0-100%)
    # decision_function: higher = more normal, lower = more anomalous
    # Normalize to [0, 1] where 1 = definitely cheating
    score_min = raw_scores.min()
    score_max = raw_scores.max()
    cheat_probs = 1.0 - (raw_scores - score_min) / (score_max - score_min + 1e-8)
    cheat_probs = np.clip(cheat_probs * 100, 0, 100)

    n_anomalies = (predictions == -1).sum()
    n_normal = (predictions == 1).sum()

    print()
    print("    --- Anomaly Detection Results ---")
    print_table(
        ["Classification", "Count", "Percentage"],
        [
            ["Normal (1)", n_normal, f"{n_normal / len(predictions) * 100:.1f}%"],
            ["Anomaly (-1)", n_anomalies, f"{n_anomalies / len(predictions) * 100:.1f}%"],
        ]
    )

    print()
    print("    --- Cheat Probability Distribution ---")
    bins = [(0, 20, 'LOW'), (20, 50, 'MODERATE'), (50, 75, 'HIGH'), (75, 100, 'CRITICAL')]
    bin_rows = []
    for lo, hi, label in bins:
        count = ((cheat_probs >= lo) & (cheat_probs < hi)).sum()
        bar = '#' * (count * 2)
        bin_rows.append([f"{lo}-{hi}%", label, count, bar])
    print_table(["Range", "Risk Level", "Sessions", "Distribution"], bin_rows)

    # Step 7d: Feature importance (approximate via permutation)
    print()
    print("    [7d] Estimating feature importance (perturbation method)...")
    base_score = model.score_samples(X_scaled).mean()
    importances = []
    for i in range(X_scaled.shape[1]):
        X_perm = X_scaled.copy()
        np.random.seed(42)
        X_perm[:, i] = np.random.permutation(X_perm[:, i])
        perm_score = model.score_samples(X_perm).mean()
        importances.append(abs(base_score - perm_score))

    importances = np.array(importances)
    imp_total = importances.sum() + 1e-8
    importances_pct = importances / imp_total

    sorted_idx = np.argsort(importances_pct)[::-1]

    print()
    print("    --- Feature Importance (Top 15) ---")
    imp_rows = []
    for rank, i in enumerate(sorted_idx[:15]):
        fname = feature_names[i]
        src = 'VISION' if fname.startswith('v_') else ('AUDIO' if fname.startswith('a_') else 'EVENT')
        bar = '#' * int(importances_pct[i] * 100)
        imp_rows.append([rank + 1, f"[{src}]", fname, f"{importances_pct[i]:.4f}", bar])
    print_table(["Rank", "Source", "Feature", "Importance", ""], imp_rows)

    return model, scaler, cheat_probs, predictions, feature_names


# ============================================================================
#  STEP 8: Z-SCORE ANOMALY ANALYSIS (Statistical Baseline)
# ============================================================================
def step8_statistical_analysis(X, feature_names, cheat_probs, sessions):
    print_header(8, "STATISTICAL ANOMALY ANALYSIS (Z-Score Baseline)")
    print()
    print("    Computing per-feature Z-scores to identify which specific")
    print("    behavioral dimensions deviate from the population baseline.")
    print()

    means = X.mean(axis=0)
    stds = X.std(axis=0) + 1e-8
    Z = np.abs((X - means) / stds)

    # Find the most anomalous sessions
    z_total = Z.sum(axis=1)
    top_anomalous = np.argsort(z_total)[::-1][:10]

    print("    --- Top 10 Most Anomalous Sessions (by total Z-score) ---")
    anom_rows = []
    for rank, idx in enumerate(top_anomalous):
        sid = sessions[idx]['session_id'][:8]
        verdict = sessions[idx]['verdict']
        z_val = z_total[idx]
        cp = cheat_probs[idx]
        # Find top deviating feature
        top_feat_idx = np.argmax(Z[idx])
        top_feat = feature_names[top_feat_idx]
        top_z = Z[idx][top_feat_idx]
        anom_rows.append([rank + 1, sid, verdict, f"{z_val:.1f}", f"{cp:.1f}%",
                          top_feat, f"{top_z:.1f}"])

    print_table(
        ["#", "Session", "Verdict", "Z-Total", "Cheat%", "Top Feature", "Z"],
        anom_rows
    )

    # Per-feature mean Z-score (which features vary most across sessions)
    feature_z_means = Z.mean(axis=0)
    sorted_fz = np.argsort(feature_z_means)[::-1]

    print()
    print("    --- Features with Highest Population Variance (Mean |Z|) ---")
    fz_rows = []
    for i in sorted_fz[:10]:
        src = 'VIS' if feature_names[i].startswith('v_') else ('AUD' if feature_names[i].startswith('a_') else 'EVT')
        fz_rows.append([src, feature_names[i], f"{feature_z_means[i]:.3f}"])
    print_table(["Src", "Feature", "Mean |Z|"], fz_rows)


# ============================================================================
#  STEP 9: MODEL EVALUATION & SAVE
# ============================================================================
def step9_evaluate_and_save(model, scaler, feature_names, cheat_probs, predictions, sessions):
    print_header(9, "MODEL EVALUATION & SAVING")
    print()

    # Compare with verdicts
    print("    Comparing unsupervised predictions with existing verdict labels...")
    print()

    verdict_groups = defaultdict(list)
    for i, sess in enumerate(sessions):
        verdict_groups[sess['verdict']].append(cheat_probs[i])

    eval_rows = []
    for verdict in ['CLEAN', 'SUSPICIOUS', 'UNKNOWN', 'CHEATING']:
        if verdict not in verdict_groups:
            continue
        probs = verdict_groups[verdict]
        eval_rows.append([
            verdict,
            len(probs),
            f"{np.mean(probs):.1f}%",
            f"{np.min(probs):.1f}%",
            f"{np.max(probs):.1f}%",
            f"{np.std(probs):.1f}%",
        ])

    print("    --- Cheat Probability by Verdict Group ---")
    print_table(
        ["Verdict", "N", "Mean Prob", "Min", "Max", "Std"],
        eval_rows
    )

    # Show per-session predictions
    print()
    print("    --- Per-Session Predictions (first 20) ---")
    pred_rows = []
    for i, sess in enumerate(sessions[:20]):
        status = "ANOMALY" if predictions[i] == -1 else "NORMAL"
        risk = "LOW" if cheat_probs[i] < 30 else ("MED" if cheat_probs[i] < 60 else "HIGH")
        pred_rows.append([
            sess['session_id'][:8],
            sess['verdict'],
            f"{cheat_probs[i]:.1f}%",
            risk,
            status,
        ])
    print_table(["Session", "Verdict", "Cheat%", "Risk", "IF Label"], pred_rows)

    # Save model
    print()
    print("    Saving model artifacts...")
    import pickle
    os.makedirs(os.path.dirname(MODEL_SAVE_PATH), exist_ok=True)
    with open(MODEL_SAVE_PATH, 'wb') as f:
        pickle.dump({
            'model': model,
            'scaler': scaler,
            'feature_names': feature_names,
            'type': 'IsolationForest',
            'n_sessions_trained': len(sessions),
        }, f)

    print(f"    Model saved to: {MODEL_SAVE_PATH}")
    print(f"    Model type: Isolation Forest (Unsupervised)")
    print(f"    Features: {len(feature_names)} (multi-modal)")
    print(f"    Sessions trained on: {len(sessions)}")

    print()
    print("=" * 70)
    print("  PIPELINE COMPLETE")
    print("=" * 70)
    print()
    print("  The model can now predict cheating probability (0-100%) for")
    print("  any new session using only behavioral signals -- no labels needed!")
    print()


# ============================================================================
#  MAIN EXECUTION
# ============================================================================
if __name__ == '__main__':
    start_time = time.time()

    print()
    print("*" * 70)
    print("*" + " " * 68 + "*")
    print("*   MULTI-MODAL CHEATING DETECTION                                 *")
    print("*   Unsupervised Learning Pipeline                                 *")
    print("*" + " " * 68 + "*")
    print("*   Data:  Event Logs + Computer Vision + Audio Analysis           *")
    print("*   Model: Isolation Forest (Anomaly Detection)                    *")
    print("*" + " " * 68 + "*")
    print("*" * 70)

    # Step 1: Load
    sessions, audio_files = step1_load_data()

    # Step 2: Clean
    sessions = step2_clean_data(sessions)

    # Step 3: Event features
    event_features = step3_extract_event_features(sessions)

    # Step 4: Vision features
    vision_features = step4_extract_vision_features(sessions)

    # Step 5: Audio features
    audio_features = step5_extract_audio_features(audio_files)

    # Step 6: Fuse
    X, feature_names = step6_fuse_features(event_features, vision_features, audio_features, sessions)

    # Step 7: Train
    model, scaler, cheat_probs, predictions, feature_names = step7_train_model(X, feature_names, sessions)

    # Step 8: Statistical analysis
    step8_statistical_analysis(X, feature_names, cheat_probs, sessions)

    # Step 9: Evaluate & Save
    step9_evaluate_and_save(model, scaler, feature_names, cheat_probs, predictions, sessions)

    elapsed = time.time() - start_time
    print(f"  Total pipeline time: {elapsed:.1f} seconds")
    print()