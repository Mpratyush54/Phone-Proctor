"""
Cheating Probability Predictor  (Multi-Modal)
Trains a Gradient Boosted model on historical session data to predict
real-time cheating probability (0-100%).

Feature sources:
 1. EVENT LOG features  - violation rates, burst density, yaw/pitch stats
 2. VISION features     - face count, head pose, eye aspect ratio, lighting
 3. AUDIO features      - RMS energy, zero-crossing rate, speech ratio
"""

import os
import json
import re
import time
import numpy as np
import pickle
from datetime import datetime, timedelta
from collections import defaultdict

try:
    import cv2
    _CV2 = True
except ImportError:
    _CV2 = False

try:
    import mediapipe as mp
    _MP = True
except ImportError:
    _MP = False

try:
    from scipy.io import wavfile as scipy_wav
    _SCIPY = True
except ImportError:
    _SCIPY = False

MODEL_PATH = os.path.join(os.path.dirname(__file__), '..', 'models', 'cheat_model.pkl')

# ──────────────────────────────────────────────────
# 1. DATA LOADER
# ──────────────────────────────────────────────────
def load_all_sessions(data_dirs=None):
    """Load all session data from data directories."""
    if data_dirs is None:
        base = os.path.join(os.path.dirname(__file__), '..', 'data')
        data_dirs = [
            os.path.join(base, 'dataset'),
            os.path.join(base, 'dataset.old'),
        ]
    
    sessions = []
    
    for d in data_dirs:
        if not os.path.exists(d):
            continue
        for session_id in os.listdir(d):
            session_path = os.path.join(d, session_id)
            if not os.path.isdir(session_path):
                continue
            
            events_file = os.path.join(session_path, 'events.jsonl')
            report_file = os.path.join(session_path, 'FINAL_REPORT.md')
            
            if not os.path.isfile(events_file):
                continue
            
            # Load events
            events = []
            with open(events_file, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        evt = json.loads(line)
                        evt['_ts'] = datetime.fromisoformat(evt['timestamp'])
                        events.append(evt)
                    except:
                        pass
            
            if not events:
                continue
            
            # Load verdict from report
            verdict = 'UNKNOWN'
            confidence = 0
            duration_sec = 0
            
            if os.path.isfile(report_file):
                with open(report_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    
                    # Extract verdict
                    if 'CLEAN' in content:
                        verdict = 'CLEAN'
                    elif 'SUSPICIOUS' in content:
                        verdict = 'SUSPICIOUS'
                    elif 'CHEATING' in content:
                        verdict = 'CHEATING'
                    
                    # Extract confidence score
                    m = re.search(r'Confidence:\s*(\d+)/100', content)
                    if m:
                        confidence = int(m.group(1))
                    
                    # Extract duration
                    m = re.search(r'Duration:\s*(\d+)\s*min\s*(\d+)\s*sec', content)
                    if m:
                        duration_sec = int(m.group(1)) * 60 + int(m.group(2))
            
            # Collect image paths from events
            image_paths = []
            for evt in events:
                ip = evt.get('image_path')
                if ip:
                    image_paths.append(ip)

            sessions.append({
                'session_id': session_id,
                'events': events,
                'verdict': verdict,
                'confidence': confidence,
                'duration_sec': duration_sec,
                'path': session_path,
                'image_paths': image_paths,
            })
    
    return sessions


# ──────────────────────────────────────────────────
# 2. VISION FEATURE EXTRACTION
# ──────────────────────────────────────────────────
def _init_face_mesh():
    """Lazily init MediaPipe FaceMesh (heavy, only call once)."""
    if not _MP or not _CV2:
        return None
    return mp.solutions.face_mesh.FaceMesh(
        static_image_mode=True,
        max_num_faces=3,
        refine_landmarks=True,
        min_detection_confidence=0.4,
    )

_face_mesh_instance = None

def _get_face_mesh():
    global _face_mesh_instance
    if _face_mesh_instance is None:
        _face_mesh_instance = _init_face_mesh()
    return _face_mesh_instance


def _eye_aspect_ratio(landmarks, indices, w, h):
    """Compute EAR for one eye given landmark indices."""
    pts = np.array([(landmarks[i].x * w, landmarks[i].y * h) for i in indices])
    # Vertical distances
    v1 = np.linalg.norm(pts[1] - pts[5])
    v2 = np.linalg.norm(pts[2] - pts[4])
    # Horizontal distance
    hz = np.linalg.norm(pts[0] - pts[3])
    return (v1 + v2) / (2.0 * hz + 1e-6)


def _head_pose_from_landmarks(landmarks, w, h):
    """Estimate yaw/pitch from 6-point solvePnP."""
    # 2D image points from key landmarks
    pts_2d = np.array([
        (landmarks[1].x * w,   landmarks[1].y * h),    # Nose tip
        (landmarks[152].x * w, landmarks[152].y * h),   # Chin
        (landmarks[33].x * w,  landmarks[33].y * h),    # Left eye corner
        (landmarks[263].x * w, landmarks[263].y * h),   # Right eye corner
        (landmarks[61].x * w,  landmarks[61].y * h),    # Left mouth
        (landmarks[291].x * w, landmarks[291].y * h),   # Right mouth
    ], dtype=np.float64)

    # Generic 3D model points
    pts_3d = np.array([
        (0.0, 0.0, 0.0),
        (0.0, -63.6, -12.5),
        (-43.3, 32.7, -26.0),
        (43.3, 32.7, -26.0),
        (-28.9, -28.9, -24.1),
        (28.9, -28.9, -24.1),
    ], dtype=np.float64)

    cam_matrix = np.array([
        [w, 0, w / 2],
        [0, w, h / 2],
        [0, 0, 1],
    ], dtype=np.float64)
    dist_coeffs = np.zeros((4, 1))

    ok, rvec, tvec = cv2.solvePnP(pts_3d, pts_2d, cam_matrix, dist_coeffs)
    if not ok:
        return 0.0, 0.0
    rmat, _ = cv2.Rodrigues(rvec)
    angles, _, _, _, _, _ = cv2.RQDecomp3x3(rmat)
    return float(angles[1]), float(angles[0])  # yaw, pitch


def extract_vision_features(image_paths, session_path):
    """
    Extract vision features from a batch of violation images.
    Returns a dict of aggregated features.
    """
    face_mesh = _get_face_mesh()
    _VISION_KEYS = [
        'v_no_face_ratio', 'v_multi_face_ratio', 'v_avg_face_count',
        'v_yaw_mean', 'v_yaw_max', 'v_yaw_std',
        'v_pitch_mean', 'v_pitch_max', 'v_pitch_std',
        'v_ear_mean', 'v_ear_min', 'v_ear_std',
        'v_face_size_mean', 'v_face_size_std',
        'v_brightness_mean', 'v_brightness_std',
        'v_images_analyzed',
    ]
    if face_mesh is None or not _CV2 or not image_paths:
        return {k: 0 for k in _VISION_KEYS}

    face_counts = []
    yaws_v, pitches_v = [], []
    ears = []  # eye aspect ratios
    face_sizes = []  # face bounding box area as fraction of frame
    brightnesses = []
    no_face_count = 0
    multi_face_count = 0

    # Sample max 100 images to keep training fast
    sample = image_paths if len(image_paths) <= 100 else [
        image_paths[i] for i in np.linspace(0, len(image_paths)-1, 100, dtype=int)
    ]

    # Left/right eye landmark indices for EAR
    L_EYE = [362, 385, 387, 263, 373, 380]
    R_EYE = [33, 160, 158, 133, 153, 144]

    for img_rel in sample:
        full_path = os.path.join(session_path, img_rel) if not os.path.isabs(img_rel) else img_rel
        if not os.path.isfile(full_path):
            continue

        img = cv2.imread(full_path)
        if img is None:
            continue

        h, w = img.shape[:2]

        # Brightness (mean luminance)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        brightnesses.append(float(np.mean(gray)) / 255.0)

        # Face Mesh
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        results = face_mesh.process(rgb)

        if not results.multi_face_landmarks:
            face_counts.append(0)
            no_face_count += 1
            continue

        n_faces = len(results.multi_face_landmarks)
        face_counts.append(n_faces)
        if n_faces >= 2:
            multi_face_count += 1

        # Use first face for detailed analysis
        lm = results.multi_face_landmarks[0].landmark

        # Head pose
        yaw, pitch = _head_pose_from_landmarks(lm, w, h)
        yaws_v.append(abs(yaw))
        pitches_v.append(abs(pitch))

        # Eye aspect ratio
        l_ear = _eye_aspect_ratio(lm, L_EYE, w, h)
        r_ear = _eye_aspect_ratio(lm, R_EYE, w, h)
        ears.append((l_ear + r_ear) / 2.0)

        # Face size (bounding box area / frame area)
        xs = [l.x for l in lm]
        ys = [l.y for l in lm]
        face_w = max(xs) - min(xs)
        face_h = max(ys) - min(ys)
        face_sizes.append(face_w * face_h)

    feats = {}
    n = max(len(sample), 1)

    feats['v_no_face_ratio'] = no_face_count / n
    feats['v_multi_face_ratio'] = multi_face_count / n
    feats['v_avg_face_count'] = float(np.mean(face_counts)) if face_counts else 0

    feats['v_yaw_mean'] = float(np.mean(yaws_v)) if yaws_v else 0
    feats['v_yaw_max'] = float(np.max(yaws_v)) if yaws_v else 0
    feats['v_yaw_std'] = float(np.std(yaws_v)) if yaws_v else 0
    feats['v_pitch_mean'] = float(np.mean(pitches_v)) if pitches_v else 0
    feats['v_pitch_max'] = float(np.max(pitches_v)) if pitches_v else 0
    feats['v_pitch_std'] = float(np.std(pitches_v)) if pitches_v else 0

    feats['v_ear_mean'] = float(np.mean(ears)) if ears else 0.3
    feats['v_ear_min'] = float(np.min(ears)) if ears else 0.3
    feats['v_ear_std'] = float(np.std(ears)) if ears else 0

    feats['v_face_size_mean'] = float(np.mean(face_sizes)) if face_sizes else 0
    feats['v_face_size_std'] = float(np.std(face_sizes)) if face_sizes else 0

    feats['v_brightness_mean'] = float(np.mean(brightnesses)) if brightnesses else 0.5
    feats['v_brightness_std'] = float(np.std(brightnesses)) if brightnesses else 0

    feats['v_images_analyzed'] = len(sample)

    return feats


# ──────────────────────────────────────────────────
# 3. AUDIO FEATURE EXTRACTION
# ──────────────────────────────────────────────────
def extract_audio_features(audio_dir):
    """
    Extract audio features from all WAV files in a directory.
    Returns a dict of aggregated features.
    """
    if not _SCIPY or not os.path.isdir(audio_dir):
        return {}

    wav_files = [f for f in os.listdir(audio_dir) if f.endswith('.wav')]
    if not wav_files:
        return {}

    all_rms = []
    all_zcr = []
    all_peak = []
    all_duration = []
    speech_segments = 0  # segments with energy above threshold
    total_segments = len(wav_files)

    for wf in wav_files:
        try:
            sr, data = scipy_wav.read(os.path.join(audio_dir, wf))
            if data.dtype != np.float32:
                data = data.astype(np.float32) / max(np.iinfo(data.dtype).max, 1)

            if len(data) == 0:
                continue

            # RMS energy
            rms = float(np.sqrt(np.mean(data ** 2)))
            all_rms.append(rms)

            # Peak amplitude
            peak = float(np.max(np.abs(data)))
            all_peak.append(peak)

            # Zero crossing rate
            zcr = float(np.sum(np.abs(np.diff(np.sign(data)))) / (2 * len(data)))
            all_zcr.append(zcr)

            # Duration
            dur = len(data) / sr
            all_duration.append(dur)

            # Simple speech detection: RMS > threshold
            if rms > 0.02:
                speech_segments += 1

        except Exception:
            continue

    feats = {}
    if not all_rms:
        # No valid audio - fill with zeros
        for k in ['a_rms_mean', 'a_rms_max', 'a_rms_std',
                   'a_zcr_mean', 'a_peak_mean', 'a_total_duration',
                   'a_speech_ratio', 'a_clip_count']:
            feats[k] = 0
        return feats

    feats['a_rms_mean'] = float(np.mean(all_rms))
    feats['a_rms_max'] = float(np.max(all_rms))
    feats['a_rms_std'] = float(np.std(all_rms))
    feats['a_zcr_mean'] = float(np.mean(all_zcr))
    feats['a_peak_mean'] = float(np.mean(all_peak))
    feats['a_total_duration'] = float(np.sum(all_duration))
    feats['a_speech_ratio'] = speech_segments / max(total_segments, 1)
    feats['a_clip_count'] = total_segments

    return feats


# ──────────────────────────────────────────────────
# 4. EVENT LOG FEATURES
# ──────────────────────────────────────────────────
def classify_event(data_str):
    """Classify event string into category."""
    if not isinstance(data_str, str):
        data_str = json.dumps(data_str)
    d = data_str.upper()
    if 'FOCUS LOST' in d:
        return 'focus_lost'
    elif 'GAZE' in d or 'LOOKING AWAY' in d:
        return 'gaze_away'
    elif 'HEAD' in d:
        return 'head_away'
    elif 'OBJECT' in d or 'LAPTOP' in d or 'PHONE' in d or 'BOOK' in d:
        return 'object'
    elif 'FACE' in d or 'NO FACE' in d or 'MULTIPLE' in d:
        return 'face_anomaly'
    elif 'AUDIO' in d:
        return 'audio'
    else:
        return 'other'


def extract_yaw_pitch(data_str):
    """Extract yaw and pitch values from event data string."""
    if not isinstance(data_str, str):
        data_str = json.dumps(data_str)
    m = re.search(r'Y:(-?\d+)', data_str)
    yaw = int(m.group(1)) if m else None
    m = re.search(r'P:(-?\d+)', data_str)
    pitch = int(m.group(1)) if m else None
    return yaw, pitch


def extract_session_features(events, duration_sec=None):
    """
    Extract feature vector from a list of events.
    Returns a dict of features that can be used for both training and inference.
    """
    if not events:
        return None
    
    # Infer duration
    if duration_sec is None or duration_sec == 0:
        if len(events) >= 2:
            duration_sec = max((events[-1]['_ts'] - events[0]['_ts']).total_seconds(), 1)
        else:
            duration_sec = 1
    
    duration_min = max(duration_sec / 60, 0.01)  # avoid div by 0
    n_events = len(events)
    
    # Categorize events
    categories = defaultdict(int)
    yaws = []
    pitches = []
    timestamps = []
    
    for evt in events:
        data = evt.get('data', '')
        cat = classify_event(data)
        categories[cat] += 1
        
        yaw, pitch = extract_yaw_pitch(data)
        if yaw is not None:
            yaws.append(abs(yaw))
        if pitch is not None:
            pitches.append(abs(pitch))
        
        timestamps.append(evt['_ts'])
    
    # ── FEATURES ──
    features = {}
    
    # F1: Rate features (events per minute)
    features['gaze_rate'] = categories['gaze_away'] / duration_min
    features['focus_rate'] = categories['focus_lost'] / duration_min
    features['head_rate'] = categories['head_away'] / duration_min
    features['object_count'] = categories['object']
    features['face_anomaly_count'] = categories['face_anomaly']
    features['audio_count'] = categories['audio']
    features['total_violations_per_min'] = n_events / duration_min
    
    # F2: Proportion features  
    features['gaze_ratio'] = categories['gaze_away'] / max(n_events, 1)
    features['focus_ratio'] = categories['focus_lost'] / max(n_events, 1)
    features['head_ratio'] = categories['head_away'] / max(n_events, 1)
    
    # F3: Yaw/Pitch statistics
    if yaws:
        features['yaw_mean'] = np.mean(yaws)
        features['yaw_max'] = np.max(yaws)
        features['yaw_std'] = np.std(yaws)
    else:
        features['yaw_mean'] = 0
        features['yaw_max'] = 0
        features['yaw_std'] = 0
    
    if pitches:
        features['pitch_mean'] = np.mean(pitches)
        features['pitch_max'] = np.max(pitches)
        features['pitch_std'] = np.std(pitches)
    else:
        features['pitch_mean'] = 0
        features['pitch_max'] = 0
        features['pitch_std'] = 0
    
    # F4: Burst density (rapid-fire violations within 3 seconds)
    burst_count = 0
    if len(timestamps) >= 2:
        sorted_ts = sorted(timestamps)
        for i in range(1, len(sorted_ts)):
            delta = (sorted_ts[i] - sorted_ts[i-1]).total_seconds()
            if delta < 3.0:
                burst_count += 1
    features['burst_density'] = burst_count / max(n_events, 1)
    
    # F5: Duration feature
    features['session_duration_min'] = duration_min
    
    # F6: Unique violation types
    features['violation_diversity'] = len([v for v in categories.values() if v > 0])
    
    # F7: Focus lost to specific apps (suspicious app detection)
    suspicious_focus = 0
    for evt in events:
        data = evt.get('data', '')
        if not isinstance(data, str):
            continue
        if 'Focus Lost' in data:
            d_lower = data.lower()
            # Suspicious: Chrome, Edge, browser, messaging, etc
            if any(x in d_lower for x in ['chrome', 'edge', 'firefox', 'whatsapp', 'telegram', 'discord', 'slack']):
                suspicious_focus += 1
    features['suspicious_app_focus'] = suspicious_focus
    
    return features


# ──────────────────────────────────────────────────
# 3. LABELING
# ──────────────────────────────────────────────────
def verdict_to_label(verdict, confidence):
    """
    Convert verdict + confidence to a cheating probability target.
    Returns: float 0.0 - 1.0
    """
    if verdict == 'CLEAN':
        return max(0.0, confidence / 200.0)  # 0-50% of range maps to 0-0.25
    elif verdict == 'SUSPICIOUS':
        return 0.3 + (confidence / 100.0) * 0.4  # Maps to 0.3-0.7
    elif verdict == 'CHEATING':
        return 0.7 + (confidence / 100.0) * 0.3  # Maps to 0.7-1.0
    else:
        return 0.5  # Unknown


# ──────────────────────────────────────────────────
# 4. MODEL
# ──────────────────────────────────────────────────
class CheatPredictor:
    def __init__(self):
        self.model = None
        self.scaler = None
        self.feature_names = None
        self.is_trained = False
        
        # Try loading saved model
        self._load_model()
    
    def _load_model(self):
        """Load pre-trained model from disk."""
        if os.path.isfile(MODEL_PATH):
            try:
                with open(MODEL_PATH, 'rb') as f:
                    data = pickle.load(f)
                self.model = data['model']
                self.scaler = data['scaler']
                self.feature_names = data['feature_names']
                self.is_trained = True
                print(f"[AI] Loaded cheat prediction model ({len(self.feature_names)} features)")
            except Exception as e:
                print(f"[AI] Failed to load model: {e}")
    
    def _save_model(self):
        """Save trained model to disk."""
        os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
        with open(MODEL_PATH, 'wb') as f:
            pickle.dump({
                'model': self.model,
                'scaler': self.scaler,
                'feature_names': self.feature_names,
            }, f)
        print(f"[AI] Model saved to {MODEL_PATH}")
    
    def train(self, data_dirs=None):
        """Train the model on all available session data."""
        from sklearn.ensemble import GradientBoostingRegressor
        from sklearn.preprocessing import StandardScaler
        from sklearn.model_selection import cross_val_score
        
        print("[AI] " + "="*40)
        print("[AI]  TRAINING CHEATING PROBABILITY MODEL")
        print("[AI] " + "="*40)
        
        # 1. Load data
        sessions = load_all_sessions(data_dirs)
        print(f"[AI] Loaded {len(sessions)} sessions")
        
        if len(sessions) < 5:
            print("[AI] ERROR: Not enough sessions to train (need >= 5)")
            return False
        
        # 2. Extract features + labels (MULTI-MODAL)
        X_data = []
        y_data = []
        skipped = 0
        
        # Audio dir is shared across sessions
        audio_dir = os.path.join(os.path.dirname(__file__), '..', 'data', 'audio')
        audio_feats_shared = extract_audio_features(audio_dir)
        if audio_feats_shared:
            print(f"[AI] Audio features extracted: {len(audio_feats_shared)} features from {audio_feats_shared.get('a_clip_count', 0)} clips")
        else:
            print("[AI] No audio data found - audio features will be zeroed")
        
        print("[AI] Extracting vision features from images (this may take a moment)...")
        
        for i, sess in enumerate(sessions):
            # A) Event log features
            features = extract_session_features(sess['events'], sess['duration_sec'])
            if features is None:
                skipped += 1
                continue
            
            # B) Vision features from violation images
            vis_feats = extract_vision_features(
                sess.get('image_paths', []),
                sess['path']
            )
            features.update(vis_feats)
            
            # C) Audio features (shared across sessions for now)
            features.update(audio_feats_shared if audio_feats_shared else {
                k: 0 for k in ['a_rms_mean', 'a_rms_max', 'a_rms_std',
                                'a_zcr_mean', 'a_peak_mean', 'a_total_duration',
                                'a_speech_ratio', 'a_clip_count']
            })
            
            label = verdict_to_label(sess['verdict'], sess['confidence'])
            X_data.append(features)
            y_data.append(label)
            
            if (i + 1) % 10 == 0:
                print(f"[AI]   Processed {i+1}/{len(sessions)} sessions...")
        
        print(f"[AI] Extracted features from {len(X_data)} sessions (skipped {skipped})")
        
        # Convert to numpy
        self.feature_names = sorted(X_data[0].keys())
        X = np.array([[f[k] for k in self.feature_names] for f in X_data])
        y = np.array(y_data)
        
        print(f"[AI] Feature matrix: {X.shape}")
        print(f"[AI] Labels: min={y.min():.2f}, max={y.max():.2f}, mean={y.mean():.2f}")
        print(f"[AI] Features: {self.feature_names}")
        
        # 3. Scale
        self.scaler = StandardScaler()
        X_scaled = self.scaler.fit_transform(X)
        
        # 4. Train Gradient Boosting Regressor (predicts continuous 0-1 probability)
        self.model = GradientBoostingRegressor(
            n_estimators=200,
            max_depth=4,
            learning_rate=0.05,
            min_samples_split=3,
            min_samples_leaf=2,
            subsample=0.8,
            random_state=42,
        )
        
        # Cross-validate
        scores = cross_val_score(self.model, X_scaled, y, cv=min(5, len(X_data)), scoring='r2')
        print(f"[AI] Cross-Validation R² scores: {[f'{s:.3f}' for s in scores]}")
        print(f"[AI] Mean R²: {scores.mean():.3f} ± {scores.std():.3f}")
        
        # Fit on all data
        self.model.fit(X_scaled, y)
        self.is_trained = True
        
        # Feature importances
        importances = self.model.feature_importances_
        sorted_idx = np.argsort(importances)[::-1]
        print("\n[AI] Feature Importances:")
        for i in sorted_idx:
            bar = '#' * int(importances[i] * 50)
            print(f"[AI]   {self.feature_names[i]:30s} {importances[i]:.4f} {bar}")
        
        # 5. Save model
        self._save_model()
        
        # 6. Show predictions on training data (for verification)
        y_pred = self.model.predict(X_scaled)
        y_pred = np.clip(y_pred, 0, 1)
        
        print(f"\n[AI] ----------- Training Predictions -----------")
        for i, sess in enumerate(sessions):
            if i >= len(y_pred):
                break
            actual_pct = y[i] * 100
            pred_pct = y_pred[i] * 100
            marker = "OK" if abs(actual_pct - pred_pct) < 15 else "!!"
            print(f"[AI]   {marker} Session {sess['session_id'][:8]}: "
                  f"Actual={actual_pct:5.1f}% Predicted={pred_pct:5.1f}% "
                  f"({sess['verdict']})")
        
        mae = np.mean(np.abs(y - y_pred)) * 100
        print(f"\n[AI] Mean Absolute Error: {mae:.1f}%")
        print("[AI] " + "="*40)
        print("[AI] MODEL TRAINED SUCCESSFULLY")
        print("[AI] " + "="*40)
        
        return True
    
    def predict(self, events, duration_sec=None):
        """
        Predict cheating probability from a list of events.
        Returns: float 0-100 (percentage)
        """
        if not self.is_trained:
            return -1  # Model not available
        
        features = extract_session_features(events, duration_sec)
        if features is None:
            return 0
        
        # Build feature vector in correct order
        x = np.array([[features.get(k, 0) for k in self.feature_names]])
        x_scaled = self.scaler.transform(x)
        
        prob = self.model.predict(x_scaled)[0]
        prob = np.clip(prob, 0, 1)
        
        return round(prob * 100, 1)
    
    def predict_realtime(self, recent_events, window_sec=60):
        """
        Predict cheating probability from the most recent N seconds of events.
        Used for the live dashboard indicator.
        """
        if not self.is_trained or not recent_events:
            return 0.0
        
        # Filter to recent window
        now = datetime.now()
        cutoff = now - timedelta(seconds=window_sec)
        windowed = [e for e in recent_events if e.get('_ts', now) >= cutoff]
        
        if not windowed:
            return 0.0
        
        return self.predict(windowed, duration_sec=window_sec)
    
    def explain(self, events, duration_sec=None):
        """
        Generate human-readable explanation of the prediction.
        Returns: dict with probability, top_factors, verdict
        """
        if not self.is_trained:
            return {'probability': -1, 'verdict': 'MODEL_NOT_TRAINED', 'factors': []}
        
        features = extract_session_features(events, duration_sec)
        if features is None:
            return {'probability': 0, 'verdict': 'NO_DATA', 'factors': []}
        
        x = np.array([[features.get(k, 0) for k in self.feature_names]])
        x_scaled = self.scaler.transform(x)
        
        prob = np.clip(self.model.predict(x_scaled)[0], 0, 1) * 100
        
        # Get feature contributions (approximate via feature values * importances)
        importances = self.model.feature_importances_
        contributions = np.abs(x_scaled[0]) * importances
        sorted_idx = np.argsort(contributions)[::-1]
        
        top_factors = []
        for i in sorted_idx[:5]:
            fname = self.feature_names[i]
            fval = features.get(fname, 0)
            imp = importances[i]
            if imp > 0.01:
                top_factors.append({
                    'feature': fname,
                    'value': round(fval, 2),
                    'importance': round(imp, 4),
                })
        
        # Verdict
        if prob < 20:
            verdict = 'CLEAN'
        elif prob < 50:
            verdict = 'LOW_RISK'
        elif prob < 70:
            verdict = 'SUSPICIOUS'
        else:
            verdict = 'HIGH_RISK'
        
        return {
            'probability': round(prob, 1),
            'verdict': verdict,
            'factors': top_factors,
        }


# ──────────────────────────────────────────────────
# 5. CLI
# ──────────────────────────────────────────────────
if __name__ == '__main__':
    import sys
    
    print("=" * 60)
    print("  CHEATING PROBABILITY MODEL - TRAINING PIPELINE")
    print("=" * 60)
    
    predictor = CheatPredictor()
    
    if '--predict' in sys.argv:
        # Predict on a specific session
        session_id = sys.argv[sys.argv.index('--predict') + 1] if len(sys.argv) > sys.argv.index('--predict') + 1 else None
        if session_id:
            sessions = load_all_sessions()
            for s in sessions:
                if s['session_id'] == session_id:
                    result = predictor.explain(s['events'], s['duration_sec'])
                    print(f"\nSession: {session_id}")
                    print(f"Probability: {result['probability']}%")
                    print(f"Verdict: {result['verdict']}")
                    print("Top Factors:")
                    for f in result['factors']:
                        print(f"  - {f['feature']}: {f['value']} (importance: {f['importance']})")
                    break
    else:
        # Train
        predictor.train()
