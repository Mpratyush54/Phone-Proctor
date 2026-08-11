"""Tests for rules/thresholds.py (YAML config loading + Thresholds facade)."""

import copy

from rules import thresholds as th


def test_load_yaml_config_returns_defaults_prefill():
    config = th.load_yaml_config()
    assert config["rules"]["face_missing_threshold_sec"] == 5
    assert config["fusion"]["weights"]["phone_face"] == 0.25
    assert "network" in config["fusion"]["weights"]
    assert config["network_integrity"]["enforce_hotspot"] is True


def test_load_yaml_config_missing_file_returns_defaults(tmp_path):
    config = th.load_yaml_config(path=str(tmp_path / "nope.yaml"))
    assert config["gaze"]["gaze_center_low"] == 0.42


def test_load_yaml_config_missing_keys_fall_back(tmp_path):
    p = tmp_path / "settings.yaml"
    p.write_text("rules:\n  look_away_threshold_sec: 1.25\n", encoding="utf-8")
    config = th.load_yaml_config(path=str(p))
    assert config["rules"]["look_away_threshold_sec"] == 1.25
    # Unrelated sections still come from defaults.
    assert config["rules"]["face_missing_threshold_sec"] == 5
    assert config["room_scan"]["base_frames"] == 15


def test_load_yaml_config_invalid_returns_defaults(tmp_path):
    p = tmp_path / "settings.yaml"
    p.write_text("not: [valid", encoding="utf-8")
    config = th.load_yaml_config(path=str(p))
    assert config["gaze"]["gaze_center_high"] == 0.58


def test_thresholds_nested_get():
    t = th.Thresholds({**copy.deepcopy(th.DEFAULT_CONFIG)})
    assert t.get("rules", "yaw_threshold_deg") == 35
    assert t.get("rules", "missing_key", default="fallback") == "fallback"


def test_thresholds_section_accessors():
    t = th.Thresholds()
    assert t.rules("look_away_threshold_sec") == 0.5
    assert t.fusion_weights()["object"] == 0.10
    assert t.warning_score() == 0.30
    assert t.flag_score() == 0.60
    assert t.network_integrity("data_spike_upload_kbs") == 80
    assert t.room_scan("change_threshold") == 0.18
    assert t.triangulation("screen_distance_cm") == 60.0
    assert t.gaze("gaze_vertical_high") == 0.60
    assert t.camera("width") == 640