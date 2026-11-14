"""E5 laptop/screen LiveKit publisher. Publishes only while a controller is subscribed."""

from __future__ import annotations


class LivePublisher:
    def __init__(self) -> None:
        self.publishing = False
        self.viewers = 0
        self.audit: list[str] = []

    def viewer_joined(self) -> None:
        self.viewers += 1
        if not self.publishing:
            self.publishing = True
            self.audit.append("START_LIVE")

    def viewer_left(self) -> str | None:
        self.viewers = max(0, self.viewers - 1)
        if self.viewers == 0 and self.publishing:
            self.publishing = False
            self.audit.append("STOP_LIVE")
            return "STOP_LIVE"
        return None
