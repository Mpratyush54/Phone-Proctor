"""F8 transparent rules + logistic baselines. Never a cheating probability."""

from __future__ import annotations

from typing import Any

LEAKAGE = frozenset({"fused_score", "verdict", "reviewer_action", "cheat_label", "session_verdict"})


def rules_score(row: dict[str, Any]) -> dict[str, float]:
    """Named event heads, not a guilt score."""
    return {
        "look_away": float(abs(row.get("gaze_h", 0)) > 0.45 or abs(row.get("head_yaw", 0)) > 25),
        "multi_face": float(row.get("face_count", 1) > 1),
        "no_face": float(row.get("face_count", 1) == 0),
    }


def evidence_quality(row: dict[str, Any]) -> float:
    missing = sum(1 for k in ("gaze_h", "head_yaw", "face_count") if row.get(k) is None)
    return max(0.0, 1.0 - 0.3 * missing)


def assert_no_leakage(features: dict[str, Any]) -> None:
    bad = LEAKAGE.intersection(features)
    if bad:
        raise ValueError(f"leakage features present: {sorted(bad)}")


def logistic_priority(heads: dict[str, float], quality: float, severity: dict[str, float] | None = None) -> float:
    severity = severity or {"look_away": 0.4, "multi_face": 0.8, "no_face": 0.6}
    raw = sum(heads.get(k, 0) * severity.get(k, 0.3) for k in heads)
    return min(1.0, raw * (0.5 + 0.5 * quality))
