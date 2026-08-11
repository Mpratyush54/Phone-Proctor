import copy
import os

try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

# Default thresholds (used when settings.yaml is missing / unparsable).
DEFAULT_CONFIG = {
    "rules": {
        "face_missing_threshold_sec": 5,
        "multiple_faces_threshold_sec": 2,
        "look_away_threshold_sec": 0.5,
        "yaw_threshold_deg": 35,
        "pitch_threshold_deg": 30,
    },
    "gaze": {
        "gaze_center_low": 0.42,
        "gaze_center_high": 0.58,
        "gaze_vertical_low": 0.40,
        "gaze_vertical_high": 0.60,
    },
    "confidence_engine": {
        "w_vad": 0.4,
        "w_lip": 0.3,
        "w_gaze": 0.3,
        "vad_threshold": 0.6,
        "lip_threshold": 0.5,
        "head_yaw_threshold_deg": 25,
        "head_pitch_threshold_deg": 20,
    },
    "fusion": {
        "weights": {
            "gaze_away": 0.20,
            "head_away": 0.20,
            "phone_face": 0.25,
            "multi_face": 0.15,
            "no_face": 0.05,
            "object": 0.10,
            "audio": 0.05,
        },
        "warning_score": 0.30,
        "flag_score": 0.60,
    },
    "network_integrity": {
        "allowed_ssids": [],
        "enforce_hotspot": True,
        "expected_devices_min": 1,
        "expected_devices_max": 3,
        "device_check_interval_sec": 10,
        "data_spike_upload_kbs": 80,
        "data_spike_download_kbs": 300,
        "data_spike_window_sec": 5,
    },
    "room_scan": {
        "scan_enabled": True,
        "base_frames": 15,
        "change_threshold": 0.18,
        "min_second_person_frames": 3,
        "restricted_classes": ["cell phone", "book", "remote", "tv"],
    },
    "triangulation": {
        "screen_distance_cm": 60.0,
        "screen_half_width_cm": 40.0,
        "screen_half_height_cm": 25.0,
        "phone_offset_x_cm": 45.0,
        "phone_offset_z_cm": 30.0,
        "gaze_cone_deg": 5.0,
    },
    "camera": {
        "width": 640,
        "height": 480,
        "fps": 30,
    },
    "audio": {
        "sample_rate": 16000,
        "chunk_size": 512,
        "noise_threshold": 0.2,
        "silence_threshold_sec": 1.5,
    },
}

# Default config file location relative to the package root.
DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "settings.yaml")


def load_yaml_config(path=None):
    """
    Loads the settings.yaml file and returns a merged config dict.
    Missing keys fall back to DEFAULT_CONFIG so the app never breaks
    on an abbreviated or outdated file.
    """
    result = copy.deepcopy(DEFAULT_CONFIG)
    if not _YAML_AVAILABLE:
        return result

    config_path = path or DEFAULT_CONFIG_PATH
    if not os.path.isfile(config_path):
        return result

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
        if not isinstance(loaded, dict):
            return result

        for section, values in loaded.items():
            if not isinstance(values, dict):
                continue
            base = result.setdefault(section, {})
            base.update(copy.deepcopy(values))
    except Exception as e:
        print(f"[CONFIG] Warning: Failed to parse {config_path}: {e}")

    return result


class Thresholds:
    """
    Central access point for all tunable thresholds.
    Wraps the merged config dict so modules read consistent values.
    """

    def __init__(self, config=None):
        if config is None:
            config = load_yaml_config()
        self.config = config

    def get(self, *path, default=None):
        """Nested lookup, e.g. thresholds.get('rules', 'look_away_threshold_sec')."""
        node = self.config
        for key in path:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    def rules(self, key, default=None):
        return self.get("rules", key, default=default)

    def fusion_weights(self):
        return self.get("fusion", "weights", default=DEFAULT_CONFIG["fusion"]["weights"])

    def warning_score(self):
        return self.get("fusion", "warning_score", default=DEFAULT_CONFIG["fusion"]["warning_score"])

    def flag_score(self):
        return self.get("fusion", "flag_score", default=DEFAULT_CONFIG["fusion"]["flag_score"])

    def network_integrity(self, key, default=None):
        return self.get("network_integrity", key, default=default)

    def room_scan(self, key, default=None):
        return self.get("room_scan", key, default=default)

    def triangulation(self, key, default=None):
        return self.get("triangulation", key, default=default)

    def confidence(self, key, default=None):
        return self.get("confidence_engine", key, default=default)

    def gaze(self, key, default=None):
        return self.get("gaze", key, default=default)

    def audio(self, key, default=None):
        return self.get("audio", key, default=default)

    def camera(self, key, default=None):
        return self.get("camera", key, default=default)