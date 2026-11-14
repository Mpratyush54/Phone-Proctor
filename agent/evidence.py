"""E8/E9 evidence bundle: pin ring-buffer hashes; never fabricate phone clips."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from agent.ring_buffer import RingBuffer, RingFrame


def transcode_placeholder(frames: list[RingFrame]) -> bytes:
    """Review-friendly stand-in. Original hashes stay in the manifest."""
    return b"WEBM" + b"".join(f.payload[:8] for f in frames)


def build_evidence_bundle(
    out_dir: Path,
    laptop: RingBuffer,
    phone: RingBuffer | None,
    *,
    now: float,
    phone_available: bool,
    policy_requires_phone: bool = False,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    laptop_frames = laptop.snapshot(pre_s=15, post_s=15, now=now)
    body: dict[str, Any] = {
        "laptop_hashes": laptop.hashes(laptop_frames),
        "phone_hashes": [],
        "phone_retrospective": "available" if phone_available else "unavailable",
        "transcode": None,
    }
    if phone_available and phone is not None:
        phone_frames = phone.snapshot(pre_s=7.5, post_s=7.5, now=now)
        body["phone_hashes"] = phone.hashes(phone_frames)
    else:
        if policy_requires_phone and not phone_available:
            body["phone_retrospective"] = "unavailable"
        # never fabricate success
        body["phone_uploaded"] = False
    review = transcode_placeholder(laptop_frames)
    (out_dir / "review.bin").write_bytes(review)
    body["transcode_sha256"] = hashlib.sha256(review).hexdigest()
    (out_dir / "manifest.json").write_text(json.dumps(body, indent=2), encoding="utf-8")
    return body
