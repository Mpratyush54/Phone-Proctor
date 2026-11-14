"""F4 copy-on-write 10s windows / 5s stride. Exclude fused_score and verdicts."""

from __future__ import annotations

from typing import Any, Iterable

DENY = frozenset({"fused_score", "verdict", "reviewer_action", "cheat_label", "session_verdict"})


def window_features(rows: list[dict[str, Any]], window_s: float = 10, stride_s: float = 5) -> list[dict[str, Any]]:
    if not rows:
        return []
    t0 = rows[0].get("t", 0)
    t1 = rows[-1].get("t", t0)
    out = []
    t = t0
    while t + window_s <= t1 + 1e-9:
        slice_rows = [r for r in rows if t <= r.get("t", 0) < t + window_s]
        feat = {
            "t0": t,
            "gaze_h_mean": _mean(slice_rows, "gaze_h"),
            "face_count_max": max((r.get("face_count") or 0) for r in slice_rows) if slice_rows else 0,
        }
        leak = DENY.intersection(feat)
        if leak:
            raise ValueError(leak)
        out.append(feat)
        t += stride_s
    return out


def _mean(rows: Iterable[dict[str, Any]], key: str) -> float:
    vals = [float(r[key]) for r in rows if r.get(key) is not None]
    return sum(vals) / len(vals) if vals else 0.0


def join_manifest(old_partitions: list[str], new_partition: str) -> list[str]:
    """Label changes do not recompute features — append a partition."""
    if new_partition in old_partitions:
        return list(old_partitions)
    return [*old_partitions, new_partition]
