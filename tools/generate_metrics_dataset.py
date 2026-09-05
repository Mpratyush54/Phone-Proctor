"""
Metrics-first synthetic training data (tools/generate_metrics_dataset.py)

Generates millions of METRICS rows for frame-level training (looking-away,
phone glance, multi-face, etc.) WITHOUT Blender images. Uses the same
geometry-driven world simulator as tools/generate_synthetic_data.py so
features match production.

Outputs per session (under --out):
    <sid>/events.jsonl
    <sid>/FINAL_REPORT.md
    <sid>/.done

Plus a flat training table (written at the end, or with --export-only):
    <out>/metrics_train.csv   features + looking-away labels
    <out>/manifest.json       counts, schema, generation args

Optional richer text events:
    Pass --phrase-bank path/to/bank.json produced by tools/build_llm_phrase_bank.py
    (small local LLM expands transcripts / room notes). Metrics themselves
    never depend on the LLM.

Usage:
    # Full-scale metrics (millions of rows), CPU-only, resumable
    python tools/generate_metrics_dataset.py --total-events 12000000 --workers 8

    # Smoke
    python tools/generate_metrics_dataset.py --smoke

    # Export table from an existing out dir (no new sessions)
    python tools/generate_metrics_dataset.py --export-only --out data/synthetic_metrics

    # Then train
    python tools/train_frame_model.py --data-dirs data/synthetic_metrics
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# Frame features used by tools/train_frame_model.py
FRAME_FEATURES = [
    "gaze_h", "gaze_v", "head_yaw", "head_pitch",
    "face_count", "phone_face", "vad_prob", "fused_score",
]

# Extra raw / label columns useful for supervised looking-away training
LABEL_COLUMNS = [
    "head_away", "gaze_away", "is_looking_away",
    "looking_at_phone", "phone_face", "face_count",
    "yaw_diff", "pitch_diff", "gaze_direction", "fused_status",
]


def _apply_phrase_bank(bank_path: str | None) -> None:
    """Optionally replace canned text lists in the generator with an LLM bank."""
    if not bank_path:
        return
    if not os.path.isfile(bank_path):
        raise SystemExit(f"[METRICS] phrase bank not found: {bank_path}")

    import tools.generate_synthetic_data as gen

    with open(bank_path, "r", encoding="utf-8") as f:
        bank = json.load(f)

    if bank.get("audio_transcripts"):
        gen.AUDIO_TRANSCRIPTS = list(bank["audio_transcripts"])
        print(f"[METRICS] phrase bank: {len(gen.AUDIO_TRANSCRIPTS)} audio transcripts")
    if bank.get("room_notes"):
        gen.ROOM_NOTES = list(bank["room_notes"])
        print(f"[METRICS] phrase bank: {len(gen.ROOM_NOTES)} room notes")
    if bank.get("focus_titles"):
        gen.FOCUS_TITLES = list(bank["focus_titles"])
        print(f"[METRICS] phrase bank: {len(gen.FOCUS_TITLES)} focus titles")


def _verdict_from_report(report_path: str) -> str:
    try:
        text = open(report_path, encoding="utf-8", errors="ignore").read()
    except OSError:
        return "UNKNOWN"
    for v in ("CHEATING", "SUSPICIOUS", "CLEAN"):
        if v in text:
            return v
    return "UNKNOWN"


def export_metrics_table(out_root: str, csv_name: str = "metrics_train.csv",
                         max_rows: int = 0) -> dict:
    """Flatten all session METRICS into one CSV with looking-away labels."""
    out_root = os.path.abspath(out_root)
    csv_path = os.path.join(out_root, csv_name)
    fieldnames = (
        ["session_id", "timestamp", "verdict"]
        + FRAME_FEATURES
        + [c for c in LABEL_COLUMNS if c not in FRAME_FEATURES]
    )

    n_rows = 0
    n_sessions = 0
    by_verdict = {"CLEAN": 0, "SUSPICIOUS": 0, "CHEATING": 0, "UNKNOWN": 0}
    looking_away = 0

    with open(csv_path, "w", encoding="utf-8", newline="") as out_f:
        writer = csv.DictWriter(out_f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()

        for sid in sorted(os.listdir(out_root)):
            sp = os.path.join(out_root, sid)
            ef = os.path.join(sp, "events.jsonl")
            if not os.path.isfile(ef):
                continue
            verdict = _verdict_from_report(os.path.join(sp, "FINAL_REPORT.md"))
            n_sessions += 1
            with open(ef, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    try:
                        e = json.loads(line)
                    except Exception:
                        continue
                    if e.get("type") != "METRICS":
                        continue
                    d = e.get("data") or {}
                    row = {
                        "session_id": sid,
                        "timestamp": e.get("timestamp", ""),
                        "verdict": verdict,
                    }
                    ok = True
                    for feat in FRAME_FEATURES:
                        v = d.get(feat)
                        if v is None or v == -1:
                            ok = False
                            break
                        row[feat] = v
                    if not ok:
                        continue
                    for col in LABEL_COLUMNS:
                        if col in row:
                            continue
                        row[col] = d.get(col, "")
                    writer.writerow(row)
                    n_rows += 1
                    by_verdict[verdict] = by_verdict.get(verdict, 0) + 1
                    if int(d.get("is_looking_away") or 0) == 1:
                        looking_away += 1
                    if max_rows and n_rows >= max_rows:
                        break
            if max_rows and n_rows >= max_rows:
                break

    manifest = {
        "out_root": out_root,
        "csv_path": csv_path,
        "n_sessions": n_sessions,
        "n_metric_rows": n_rows,
        "looking_away_rows": looking_away,
        "looking_away_frac": round(looking_away / max(n_rows, 1), 4),
        "by_verdict": by_verdict,
        "frame_features": FRAME_FEATURES,
        "label_columns": LABEL_COLUMNS,
    }
    man_path = os.path.join(out_root, "manifest.json")
    with open(man_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"[METRICS] wrote {n_rows:,} rows -> {csv_path}")
    print(f"[METRICS] looking_away={looking_away:,} "
          f"({manifest['looking_away_frac']:.1%}) sessions={n_sessions}")
    print(f"[METRICS] manifest -> {man_path}")
    return manifest


def run_generation(args) -> None:
    """Delegate session generation to generate_synthetic_data (metrics-only defaults)."""
    import tools.generate_synthetic_data as gen

    _apply_phrase_bank(args.phrase_bank)

    # Build argv for the existing resumable generator. No Blender / no images
    # unless the user explicitly asks for a small rich subset.
    argv = [
        "generate_synthetic_data.py",
        "--total-events", str(args.total_events),
        "--ratio", args.ratio,
        "--workers", str(args.workers),
        "--seed", str(args.seed),
        "--out", args.out,
        "--metrics-hz", str(args.metrics_hz),
        "--fps", str(args.fps),
        "--renderer", "warp",
        "--rich-sessions", str(args.rich_sessions),
        "--audio-engine", args.audio_engine,
    ]
    if args.max_sessions:
        argv += ["--max-sessions", str(args.max_sessions)]
    if args.face_crops:
        argv += ["--face-crops", args.face_crops]
    if args.smoke:
        argv.append("--smoke")

    print("[METRICS] launching generator:")
    print("  " + " ".join(argv[1:]))
    old = sys.argv
    try:
        sys.argv = argv
        gen.main()
    finally:
        sys.argv = old


def main():
    ap = argparse.ArgumentParser(
        description="Generate millions of METRICS rows for looking-away / frame training")
    ap.add_argument("--total-events", type=int, default=12_000_000,
                    help="target METRICS rows (default 12,000,000)")
    ap.add_argument("--ratio", default="60:25:15",
                    help="CLEAN:SUSPICIOUS:CHEATING session mix")
    ap.add_argument("--workers", type=int, default=8,
                    help="CPU workers (no GPU needed for metrics-only)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="data/synthetic_metrics")
    ap.add_argument("--metrics-hz", type=float, default=2.0)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--max-sessions", type=int, default=0,
                    help="hard cap on sessions (0 = auto from total-events)")
    ap.add_argument("--rich-sessions", type=int, default=0,
                    help="optional warp face-crop sessions (0 = metrics only, recommended)")
    ap.add_argument("--face-crops", default=None,
                    help="LFW crops dir if --rich-sessions > 0")
    ap.add_argument("--audio-engine", choices=["none", "edge-tts", "pyttsx3"],
                    default="none")
    ap.add_argument("--phrase-bank", default=None,
                    help="JSON from tools/build_llm_phrase_bank.py for richer text events")
    ap.add_argument("--smoke", action="store_true",
                    help="tiny run (~4k metrics) to validate the pipeline")
    ap.add_argument("--export-only", action="store_true",
                    help="only build metrics_train.csv from an existing --out")
    ap.add_argument("--skip-export", action="store_true",
                    help="generate sessions but skip the flat CSV export")
    ap.add_argument("--export-max-rows", type=int, default=0,
                    help="cap CSV rows (0 = all)")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)

    if not args.export_only:
        t0 = time.time()
        run_generation(args)
        print(f"[METRICS] generation wall time: {time.time() - t0:.0f}s")

    if not args.skip_export:
        export_metrics_table(args.out, max_rows=args.export_max_rows)


if __name__ == "__main__":
    main()
