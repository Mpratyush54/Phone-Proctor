"""Fail-closed consent enforcement.

Policy cannot enable a capability the student declined. Required capability
failure blocks the session; optional failure degrades readiness.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable

log = logging.getLogger("agent.consent")


class Capability(str, Enum):
    MICROPHONE = "microphone"
    SCREEN = "screen"
    KEYSTROKES = "keystrokes"
    CAMERA = "camera"
    NETWORK_MONITOR = "network_monitor"


REQUIRED_CAPABILITIES = frozenset({Capability.CAMERA})
OPTIONAL_CAPABILITIES = frozenset(Capability) - REQUIRED_CAPABILITIES


class Readiness(str, Enum):
    READY = "READY"
    DEGRADED = "DEGRADED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class ConsentRecord:
    microphone: bool = False
    screen: bool = False
    keystrokes: bool = False
    camera: bool = False
    network_monitor: bool = False

    def granted(self, cap: Capability) -> bool:
        return bool(getattr(self, cap.value))

    @classmethod
    def from_dict(cls, data: dict | None) -> "ConsentRecord":
        data = data or {}
        return cls(
            microphone=bool(data.get("microphone", False)),
            screen=bool(data.get("screen", False)),
            keystrokes=bool(data.get("keystrokes", False)),
            camera=bool(data.get("camera", False)),
            network_monitor=bool(data.get("network_monitor", False)),
        )


@dataclass
class ConsentDecision:
    readiness: Readiness
    allowed: set[Capability] = field(default_factory=set)
    declined: set[Capability] = field(default_factory=set)
    degraded: list[str] = field(default_factory=list)
    blocked_reason: str | None = None

    def may_start(self, cap: Capability) -> bool:
        return cap in self.allowed


class ConsentGate:
    """Evaluates policy ∩ consent. Always fail closed."""

    def evaluate(
        self,
        consent: ConsentRecord,
        policy_enabled: Iterable[Capability] | None = None,
    ) -> ConsentDecision:
        wanted = set(policy_enabled) if policy_enabled is not None else set(Capability)
        allowed: set[Capability] = set()
        declined: set[Capability] = set()
        degraded: list[str] = []

        for cap in Capability:
            if cap not in wanted:
                continue
            if consent.granted(cap):
                allowed.add(cap)
            else:
                declined.add(cap)
                if cap in REQUIRED_CAPABILITIES:
                    log.warning("required capability declined", extra={"capability": cap.value})
                    return ConsentDecision(
                        readiness=Readiness.BLOCKED,
                        allowed=set(),
                        declined=declined,
                        blocked_reason=f"required capability declined: {cap.value}",
                    )
                degraded.append(f"optional capability declined: {cap.value}")

        readiness = Readiness.DEGRADED if degraded else Readiness.READY
        return ConsentDecision(
            readiness=readiness,
            allowed=allowed,
            declined=declined,
            degraded=degraded,
        )

    def assert_may_start(self, decision: ConsentDecision, cap: Capability) -> None:
        if not decision.may_start(cap):
            raise PermissionError(f"capability {cap.value} is not consented")
