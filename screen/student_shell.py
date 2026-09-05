"""Minimal product UI stand-in. No PyQt required.

Product screens show enrollment, consent, exam content, connection status,
controller warnings, and pause/end/completion — not AI debug scores.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("screen.student_shell")


class StudentShell:
    """Print/log exam status. ``set_lifecycle`` is the supervisor-facing API."""

    def __init__(self) -> None:
        self.lifecycle: str | None = None
        self.events: list[str] = []

    def set_lifecycle(self, state: Any) -> None:
        value = state.value if hasattr(state, "value") else str(state)
        self.lifecycle = value
        self.events.append(value)
        log.info("exam status: %s", value)
        print(f"[student-shell] exam status: {value}", flush=True)
