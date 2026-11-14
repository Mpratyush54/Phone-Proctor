"""F6b missingness, transport, detector observation, counterfactual pairs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Observation:
    pair_id: str
    split: str
    sensor_ok: bool
    reconnect: bool
    clock_skew_ms: float
    detector_p_detect: float
    counterfactual: bool


def same_split(a: Observation, b: Observation) -> bool:
    return a.pair_id == b.pair_id and a.split == b.split


def apply_missingness(p_detect: float, sensor_ok: bool) -> float:
    return p_detect if sensor_ok else 0.0
