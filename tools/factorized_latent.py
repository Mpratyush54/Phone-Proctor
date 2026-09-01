"""F6 factorized latent components. Never generates a CHEATING label."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


DOMAINS = ("behavior", "environment", "device", "policy")


@dataclass(frozen=True)
class Latent:
    pair_id: str
    behavior: str
    environment: str
    device: str
    policy: str
    pose_yaw: float
    pose_pitch: float
    velocity: float
    missingness: str = "none"
    split: str = "train"


IMPOSSIBLE = {
    ("eyes_closed", "reading_screen"),
    ("no_camera", "high_fps_required"),
}


def validate(latent: Latent) -> None:
    combo = (latent.behavior, latent.policy)
    if combo in IMPOSSIBLE:
        raise ValueError(f"impossible combination {combo}")
    if abs(latent.velocity) > 180:
        raise ValueError("velocity out of range")


def preserve_pose(prev: Latent, nxt: Latent) -> Latent:
    return Latent(
        pair_id=nxt.pair_id,
        behavior=nxt.behavior,
        environment=nxt.environment,
        device=nxt.device,
        policy=nxt.policy,
        pose_yaw=prev.pose_yaw,
        pose_pitch=prev.pose_pitch,
        velocity=prev.velocity,
        missingness=nxt.missingness,
        split=prev.split,
    )


def pair_split_consistent(members: Iterable[Latent]) -> bool:
    splits = {m.split for m in members}
    pairs = {m.pair_id for m in members}
    return len(splits) == 1 and len(pairs) == 1
