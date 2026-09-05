"""F9 shadow scoring: failure never stops the exam; rollback is one alias write."""

from __future__ import annotations

from typing import Any, Callable


def shadow_score(payload: dict[str, Any], scorer: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any] | None:
    try:
        out = scorer(payload)
        out.pop("cheat_probability", None)
        return out
    except Exception:
        return None
