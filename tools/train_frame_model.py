"""
Global Frame Model Trainer (tools/train_frame_model.py)

Trains a single per-frame anomaly detector over METRICS rows collected across
ALL sessions (real data/dataset* and synthetic data/synthetic). This is the
"frame-level" counterpart to the per-session session model in
ai/ml_model.py: instead of isolating outliers within one candidate's own
session, it learns what a normal frame looks like globally and flags abnormal
frames (head turns, phone glances, no-face, etc.).

Features (same columns emitted by both proctor_thread.py and the synthetic
generator):
    gaze_h, gaze_v, head_yaw, head_pitch, face_count, phone_face, vad_prob, fused_score

For training speed the matrix is subsampled (default up to 1,000,000 rows,
stratified-ish random sample with a fixed seed so retraining is reproducible).
IsolationForest is used with max_samples=256 (per the memory guardrail).

Output:
    models/frame_model.pkl   joblib: {"clf", "scaler", "feature_names", "train_size"}

Usage:
    python tools/train_frame_model.py                          # train on all data
    python tools/train_frame_model.py --max-rows 200000        # smaller/faster
    python tools/train_frame_model.py --fast                    # smoke run
"""

import argparse
import json
import os
import sys

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

FEATURES = ["gaze_h", "gaze_v", "head_yaw", "head_pitch",
            "face_count", "phone_face", "vad_prob", "fused_score"]


def default_data_dirs():
    base = os.path.join(_PROJECT_ROOT, "data")
    return [os.path.join(base, "dataset"), os.path.join(base, "dataset.old"),
            os.path.join(base, "synthetic")]


def iter_sessions(data_dirs):
    """Yields (sid, events_file, verdict) for every valid session dir."""
    for d in data_dirs:
        if not os.path.isdir(d):
            continue
        for sid in sorted(os.listdir(d)):
            sp = os.path.join(d, sid)
            if not os.path.isdir(sp):
                continue
            ef = os.path.join(sp, "events.jsonl")
            rf = os.path.join(sp, "FINAL_REPORT.md")
            if not os.path.isfile(ef):
                continue
            verdict = "UNKNOWN"
            if os.path.isfile(rf):
                try:
                    content = open(rf, encoding="utf-8", errors="ignore").read()
                    if "CLEAN" in content:
                        verdict = "CLEAN"
                    elif "SUSPICIOUS" in content:
                        verdict = "SUSPICIOUS"
                    elif "CHEATING" in content:
                        verdict = "CHEATING"
                except Exception:
                    pass
            yield sid, ef, verdict


def load_matrix(data_dirs, max_rows, rng):
    """Streams METRICS rows into (X, labels, per_session_counts)."""
    X_rows = []
    labels = []
    session_counts = {}
    total_lines = 0

    for sid, ef, verdict in iter_sessions(data_dirs):
        count = 0
        try:
            with open(ef, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    total_lines += 1
                    try:
                        e = json.loads(line)
                    except Exception:
                        continue
                    if e.get("type") != "METRICS":
                        continue
                    d = e.get("data") or {}
                    row = []
                    ok = True
                    for feat in FEATURES:
                        v = d.get(feat)
                        if v is None or v == -1:
                            ok = False
                            break
                        row.append(float(v))
                    if not ok:
                        continue
                    X_rows.append(row)
                    labels.append(verdict)
                    count += 1
        except Exception:
            continue
        session_counts[sid] = count

    if not X_rows:
        raise SystemExit("[FRAME] No METRICS rows found in any data dir. "
                         "Run tools/generate_synthetic_data.py first.")

    X = np.asarray(X_rows, dtype=np.float64)
    labels = np.asarray(labels)

    # Subsample deterministically for a bounded, fast training set.
    if len(X) > max_rows:
        idx = rng.choice(len(X), size=max_rows, replace=False)
        idx.sort()
        X = X[idx]
        labels = labels[idx]

    print(f"[FRAME] Scanned {total_lines} event lines, collected {X.shape[0]} metric rows "
          f"from {len(session_counts)} sessions ({max_rows} cap)")
    return X, labels, session_counts


def main():
    ap = argparse.ArgumentParser(description="Train global frame-level anomaly model")
    ap.add_argument("--max-rows", type=int, default=1_000_000,
                    help="max training rows (random subsample; default 1,000,000)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default=os.path.join(_PROJECT_ROOT, "models", "frame_model.pkl"))
    ap.add_argument("--data-dirs", nargs="*", default=None,
                    help="override data directories (default: dataset, dataset.old, synthetic)")
    ap.add_argument("--fast", action="store_true", help="smoke run with 50k rows")
    args = ap.parse_args()

    if args.fast:
        args.max_rows = min(args.max_rows, 50_000)

    dirs = args.data_dirs or default_data_dirs()
    rng = np.random.default_rng(args.seed)
    X, labels, counts = load_matrix(dirs, args.max_rows, rng)

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    clf = IsolationForest(n_estimators=200, max_samples=256,
                          contamination=0.1, random_state=args.seed, n_jobs=-1)
    clf.fit(X_scaled)
    preds = clf.predict(X_scaled)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    joblib.dump({"clf": clf, "scaler": scaler, "feature_names": FEATURES,
                 "train_size": int(len(X))}, args.out)
    print(f"[FRAME] Saved model to {args.out}")

    # Per-verdict anomaly fraction (sanity check: CLEAN low, CHEATING high).
    print("[FRAME] Anomaly fraction by session verdict:")
    for v in ["CLEAN", "SUSPICIOUS", "CHEATING", "UNKNOWN"]:
        mask = labels == v
        n = int(mask.sum())
        if n == 0:
            continue
        frac = float((preds[mask] == -1).mean())
        print(f"  {v:<12} n={n:>9,}  anomaly_frac={frac:.3f}")

    print(f"[FRAME] Sessions loaded: {len(counts)}")


if __name__ == "__main__":
    main()
