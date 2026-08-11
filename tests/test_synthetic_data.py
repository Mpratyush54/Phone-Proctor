import json
import math
import os
import shutil
import tempfile

import numpy as np
import pytest

from tools.generate_synthetic_data import (
    DURATION_RANGES,
    _generate_session,
    make_record,
    sid_for,
    rng_for,
)
from tools.world_simulator import HeadTrajectory, SessionSimulator


# ---------------------------------------------------------------------------
# World simulator invariants
# ---------------------------------------------------------------------------
def _session_metrics(profile, seconds=90, seed=7):
    traj = HeadTrajectory(profile, seed=seed)
    st = traj.build(seconds)
    sim = SessionSimulator(profile=profile, seed=seed + 1)
    rows = []
    for i in range(0, st["n"], 15):
        state = {
            "yaw": st["yaw"][i], "pitch": st["pitch"][i], "roll": st["roll"][i],
            "gaze_lr": st["gaze_lr"][i], "gaze_ud": st["gaze_ud"][i],
            "face_count": int(st["face_count"][i]), "vad": st["vad"][i], "lip": st["lip"][i],
        }
        ry, rp, _, gz, pv = sim.raw_measure(
            state["yaw"], state["pitch"], state["roll"], state["gaze_lr"], state["gaze_ud"])
        y, p = sim.smooth(ry, rp)
        rows.append(sim.build_metric(y, p, ry, rp, gz, pv, state))
    return rows


def test_metric_row_has_core_columns():
    rows = _session_metrics("CLEAN")
    row = rows[0]
    for key in ("gaze_h", "gaze_v", "head_yaw", "head_pitch", "face_count"):
        assert key in row
        assert isinstance(row[key], (int, float))
    assert isinstance(row["face_count"], int)


def test_clean_profile_stays_neutral():
    rows = _session_metrics("CLEAN")
    assert max(abs(r["yaw_diff"]) for r in rows) < 35
    assert max(abs(r["pitch_diff"]) for r in rows) < 30
    assert all(r["head_away"] == 0 for r in rows)
    assert max(r["fused_score"] for r in rows) < 0.3


def test_cheating_profile_produces_strong_signals():
    rows = _session_metrics("CHEATING", seconds=180)
    assert any(r["head_away"] for r in rows)
    assert max(r["fused_score"] for r in rows) >= 0.5
    assert any(r["phone_face"] for r in rows)


def test_simulator_is_deterministic():
    a = _session_metrics("SUSPICIOUS", seconds=60, seed=11)
    b = _session_metrics("SUSPICIOUS", seconds=60, seed=11)
    assert a == b


def test_calibration_baseline_near_zero():
    sim = SessionSimulator(profile="CLEAN", seed=1)
    assert abs(sim.baseline_yaw) < 3.0
    assert abs(sim.baseline_pitch) < 3.0


def test_phone_visible_at_neutral_is_false():
    sim = SessionSimulator(profile="CLEAN", seed=1)
    assert sim._phone_visible_deg(0.0, 0.0) > 40.0
    assert sim._phone_visible_deg(-45.0, 0.0) < 40.0


def test_trajectory_shapes_and_ranges():
    st = HeadTrajectory("CHEATING", seed=3).build(120)
    assert st["yaw"].shape == (120 * 30,)
    assert np.isfinite(st["yaw"]).all() and np.isfinite(st["pitch"]).all()
    assert set(np.unique(st["face_count"])) <= {0, 1, 2}


# ---------------------------------------------------------------------------
# Generator determinism + resume correctness
# ---------------------------------------------------------------------------
@pytest.fixture
def gen_args(tmp_path):
    return {
        "seed": 42, "out_root": str(tmp_path), "fps": 30, "metrics_hz": 2.0,
        "profiles": [{"name": "CLEAN", "weight": 1.0}],
        "rich_sessions": 0, "face_crops": None, "image_stride": 10,
    }


def test_sid_and_rng_deterministic():
    assert sid_for(42, 3) == sid_for(42, 3)
    assert sid_for(42, 3) != sid_for(42, 4)
    a = rng_for(1, 2).integers(0, 10**9)
    b = rng_for(1, 2).integers(0, 10**9)
    assert a == b


def test_generate_session_writes_full_session(gen_args):
    DURATION_RANGES["CLEAN"] = (20, 30)
    stats = _generate_session(gen_args, 0)
    sid = sid_for(42, 0)
    out = os.path.join(gen_args["out_root"], sid)
    assert os.path.isfile(os.path.join(out, "events.jsonl"))
    assert os.path.isfile(os.path.join(out, "FINAL_REPORT.md"))
    assert os.path.isfile(os.path.join(out, ".done"))
    assert stats["n_metrics"] > 0
    assert stats["profile"] == "CLEAN"

    events = [json.loads(l) for l in open(os.path.join(out, "events.jsonl"), encoding="utf-8")]
    types = {e["type"] for e in events}
    assert "METRICS" in types and "INFO" in types
    assert all(e["session_id"] == sid for e in events)


def test_generate_session_resume_skips_done(gen_args):
    DURATION_RANGES["CLEAN"] = (20, 30)
    _generate_session(gen_args, 0)
    # Re-running must skip (returns None) but not corrupt existing data.
    assert _generate_session(gen_args, 0) is None
    sid = sid_for(42, 0)
    out = os.path.join(gen_args["out_root"], sid)
    n_lines_before = sum(1 for _ in open(os.path.join(out, "events.jsonl"), encoding="utf-8"))
    _generate_session(gen_args, 0)
    n_lines_after = sum(1 for _ in open(os.path.join(out, "events.jsonl"), encoding="utf-8"))
    assert n_lines_before == n_lines_after


def test_report_is_emoji_free_and_parses(gen_args):
    DURATION_RANGES["CLEAN"] = (20, 30)
    _generate_session(gen_args, 0)
    content = open(os.path.join(gen_args["out_root"], sid_for(42, 0), "FINAL_REPORT.md"),
                   encoding="utf-8").read()
    for ch in content:
        assert ord(ch) < 0x2600, f"emoji/color marker found in report: {ch!r}"
    import re
    assert "Verdict:" in content and "CLEAN" in content
    assert re.search(r"Confidence:\s*\**\s*(\d+)/100", content)
    assert re.search(r"Duration:\s*\**\s*(\d+)\s*min\s*(\d+)\s*sec", content)


def test_metric_rows_have_core_fields_in_events(gen_args):
    DURATION_RANGES["CLEAN"] = (20, 30)
    _generate_session(gen_args, 0)
    events_path = os.path.join(gen_args["out_root"], sid_for(42, 0), "events.jsonl")
    for line in open(events_path, encoding="utf-8"):
        e = json.loads(line)
        if e["type"] == "METRICS":
            for key in ("gaze_h", "gaze_v", "head_yaw", "face_count"):
                assert key in e["data"]


def test_make_record_shape():
    from datetime import datetime
    rec = make_record("X", datetime(2026, 1, 1), "INFO", {"a": 1})
    assert set(rec) == {"timestamp", "session_id", "type", "image_path", "data"}
    assert rec["image_path"] is None
