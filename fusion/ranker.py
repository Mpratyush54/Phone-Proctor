"""F8b calibrated multi-label heads + priority ranker (GBM-like, numpy)."""

from __future__ import annotations

import math
from typing import Any

from fusion.baselines import evidence_quality, logistic_priority, rules_score


def sigmoid(x: float) -> float:
    if x < -20:
        return 0.0
    if x > 20:
        return 1.0
    return 1.0 / (1.0 + math.exp(-x))


def calibrated_heads(row: dict[str, Any], temperature: float = 1.0) -> dict[str, float]:
    rules = rules_score(row)
    return {k: sigmoid((v - 0.5) / max(temperature, 1e-3)) for k, v in rules.items()}


def rank(rows: list[dict[str, Any]], budget: int) -> list[int]:
    scored = []
    for i, row in enumerate(rows):
        heads = calibrated_heads(row)
        q = evidence_quality(row)
        scored.append((logistic_priority(heads, q), i))
    scored.sort(reverse=True)
    return [i for _, i in scored[:budget]]
