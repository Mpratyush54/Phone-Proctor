"""F7 closed-loop rendered detector execution vs geometry_fast."""

from __future__ import annotations

from typing import Any, Callable

ALLOWED_MODES = ("geometry_fast", "closed_loop_rendered")


def run_pipeline(mode: str, sample: dict[str, Any], detector: Callable[[bytes], dict[str, Any]] | None = None) -> dict[str, Any]:
    if mode not in ALLOWED_MODES:
        raise ValueError(mode)
    if mode == "geometry_fast":
        return {"mode": mode, "train_pixel_model": False, "gaze_h": sample.get("gaze_h", 0)}
    pixels = sample.get("pixels")
    if not isinstance(pixels, (bytes, bytearray)):
        raise ValueError("closed_loop_rendered requires pixels")
    det = detector(bytes(pixels)) if detector else {"ok": True}
    return {"mode": mode, "train_pixel_model": True, "detector": det}
