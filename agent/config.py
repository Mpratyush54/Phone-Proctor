"""Environment flags from docs/feature-flags.md."""

from __future__ import annotations

import os
from dataclasses import dataclass

from agent.product_mode import ProductMode, current_mode, google_stt_enabled

MODE_ENV = "PHONE_PROCTOR_MODE"
WAIT_EXAM_START_ENV = "PHONE_PROCTOR_WAIT_EXAM_START"
GOOGLE_STT_ENV = "PHONE_PROCTOR_GOOGLE_STT"
REDIS_URL_ENV = "REDIS_URL"
LIVEKIT_URL_ENV = "LIVEKIT_URL"

# Server-side model alias (not an agent env var); documented rollback is PUT /api/v1/models/live.
MODEL_ALIAS_LIVE = "live"


def _env_flag(name: str, default: str = "0") -> bool:
    return (os.environ.get(name) or default).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class AgentConfig:
    mode: ProductMode
    wait_exam_start: bool
    google_stt: bool
    redis_url: str | None
    livekit_url: str | None


def load_config() -> AgentConfig:
    """Read current process env. Defaults match docs/feature-flags.md."""
    redis = (os.environ.get(REDIS_URL_ENV) or "").strip() or None
    livekit = (os.environ.get(LIVEKIT_URL_ENV) or "").strip() or None
    return AgentConfig(
        mode=current_mode(),
        wait_exam_start=_env_flag(WAIT_EXAM_START_ENV, "0"),
        google_stt=google_stt_enabled(),
        redis_url=redis,
        livekit_url=livekit,
    )
