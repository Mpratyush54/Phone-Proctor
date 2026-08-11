"""Tests for utils/logger.py (structured JSONL event logging)."""

import json
import os

import numpy as np

from utils.logger import EventLogger


def test_logger_creates_session_directory(tmp_path):
    logger = EventLogger(base_dir=str(tmp_path))
    assert logger.log_file.startswith(str(tmp_path))
    assert logger.log_file.endswith("events.jsonl")


def test_log_writes_jsonl(tmp_path):
    logger = EventLogger(base_dir=str(tmp_path))
    logger.log("VIOLATION", "Multiple Faces Detected")
    logger.log("METRICS", {"gaze_h": 0.5})
    logger.log("INFO", "session started")

    with open(logger.log_file, "r", encoding="utf-8") as f:
        lines = [json.loads(line) for line in f if line.strip()]

    assert len(lines) == 3
    assert lines[0]["type"] == "VIOLATION"
    assert lines[0]["data"] == "Multiple Faces Detected"
    assert lines[0]["session_id"] == logger.session_id
    assert lines[1]["data"]["gaze_h"] == 0.5
    assert lines[1]["image_path"] is None


def test_log_saves_frame_image(tmp_path):
    logger = EventLogger(base_dir=str(tmp_path))
    frame = np.zeros((64, 64, 3), dtype=np.uint8)
    logger.log("VIOLATION", "look away", frame=frame)

    with open(logger.log_file, "r", encoding="utf-8") as f:
        record = json.loads(f.readline())

    assert record["image_path"] is not None
    img_path = os.path.join(logger.session_dir, record["image_path"])
    assert os.path.exists(img_path)


def test_unique_session_ids(tmp_path):
    a = EventLogger(base_dir=str(tmp_path))
    b = EventLogger(base_dir=str(tmp_path))
    assert a.session_id != b.session_id