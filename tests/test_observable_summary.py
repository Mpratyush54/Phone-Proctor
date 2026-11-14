"""A4 observable session summary — evidence only, never a guilt verdict."""

import json

from analysis.observable_summary import VERDICT_FORBIDDEN, ObservableSessionSummary
from analysis.session_analyzer import SessionAnalyzer


def test_report_contains_evidence_not_guilt(tmp_path):
    log = tmp_path / "events.jsonl"
    events = [
        {"timestamp": "2026-01-01T00:00:00", "type": "INFO", "data": "session started"},
        {"timestamp": "2026-01-01T00:00:05", "type": "VIOLATION", "data": "Focus Lost: Notes"},
        {"timestamp": "2026-01-01T00:01:00", "type": "METRICS", "data": {"gaze_h": 0.1, "gaze_v": 0.0, "head_yaw": 1, "head_pitch": 0, "face_count": 1}},
    ]
    log.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
    summary = ObservableSessionSummary(tmp_path)
    result = summary.analyze()
    text = summary.report_file.read_text(encoding="utf-8")
    for banned in VERDICT_FORBIDDEN:
        assert banned not in text
    assert "evidence" in text.lower() or "observation" in text.lower()
    assert result["counts"]["VIOLATION"] == 1


def test_session_analyzer_wrapper_has_no_cheat_detected(tmp_path):
    (tmp_path / "events.jsonl").write_text(
        json.dumps({"timestamp": "2026-01-01T00:00:00", "type": "INFO", "data": "ok"}) + "\n",
        encoding="utf-8",
    )
    analyzer = SessionAnalyzer(tmp_path)
    analyzer.analyze()
    text = (tmp_path / "FINAL_REPORT.md").read_text(encoding="utf-8")
    assert "CHEAT DETECTED" not in text
    assert "CLEAN" not in text or "evidence" in text.lower()
