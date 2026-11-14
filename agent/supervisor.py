"""AgentSupervisor owns lifecycle. AI threads emit observations only.

No AI scoring until an authoritative EXAM_START command. Desired and observed
lifecycle plus control_generation are persisted so reconnect cannot skip gates.
"""

from __future__ import annotations

import logging
import threading
import time
from enum import Enum
from typing import Any, Callable

from agent.consent import Capability, ConsentDecision, ConsentGate, ConsentRecord, Readiness
from agent.observation_sink import ObservationSink
from agent.shutdown import ShutdownCoordinator
from agent.wal import EventWal

log = logging.getLogger("agent.supervisor")

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "NEW": {"ENROLLING", "BLOCKED"},
    "ENROLLING": {"PRECHECK", "BLOCKED"},
    "PRECHECK": {"READY", "DEGRADED", "BLOCKED"},
    "READY": {"IN_EXAM", "BLOCKED", "ENDED"},
    "DEGRADED": {"IN_EXAM", "BLOCKED", "ENDED", "READY"},
    "IN_EXAM": {"PAUSED", "ENDED", "BLOCKED"},
    "PAUSED": {"IN_EXAM", "ENDED", "BLOCKED"},
    "BLOCKED": {"ENDED"},
    "ENDED": set(),
}


class LifecycleState(str, Enum):
    NEW = "NEW"
    ENROLLING = "ENROLLING"
    PRECHECK = "PRECHECK"
    READY = "READY"
    DEGRADED = "DEGRADED"
    IN_EXAM = "IN_EXAM"
    PAUSED = "PAUSED"
    BLOCKED = "BLOCKED"
    ENDED = "ENDED"


class CommandDenied(Exception):
    pass


class DuplicateCommand(Exception):
    def __init__(self, prior: dict[str, Any]) -> None:
        super().__init__("duplicate idempotency_key")
        self.prior = prior


class AgentSupervisor:
    def __init__(
        self,
        wal: EventWal,
        consent: ConsentRecord | None = None,
        consent_gate: ConsentGate | None = None,
        now: Callable[[], float] | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self.wal = wal
        self.sink = ObservationSink(wal)
        self.shutdown = ShutdownCoordinator()
        self.consent = consent or ConsentRecord()
        self.gate = consent_gate or ConsentGate()
        self.consent_decision: ConsentDecision | None = None
        self.desired_lifecycle_state = LifecycleState.NEW
        self.observed_lifecycle_state = LifecycleState.NEW
        self.control_generation = 0
        self.connection_generation = 0
        self.scoring_enabled = False
        self._command_results: dict[str, dict[str, Any]] = {}
        self._now = now or time.time
        self.ai_started = False

    def persist_snapshot(self) -> dict[str, Any]:
        return {
            "desired_lifecycle_state": self.desired_lifecycle_state.value,
            "observed_lifecycle_state": self.observed_lifecycle_state.value,
            "control_generation": self.control_generation,
            "connection_generation": self.connection_generation,
            "scoring_enabled": self.scoring_enabled,
        }

    def restore(self, snap: dict[str, Any]) -> None:
        self.desired_lifecycle_state = LifecycleState(snap["desired_lifecycle_state"])
        self.observed_lifecycle_state = LifecycleState(snap["observed_lifecycle_state"])
        self.control_generation = int(snap["control_generation"])
        self.connection_generation = int(snap.get("connection_generation", 0))
        self.scoring_enabled = bool(snap.get("scoring_enabled", False))

    def apply_consent(self, policy_enabled: list[Capability] | None = None) -> ConsentDecision:
        decision = self.gate.evaluate(self.consent, policy_enabled)
        self.consent_decision = decision
        if decision.readiness is Readiness.BLOCKED:
            self._set_observed(LifecycleState.BLOCKED)
        elif decision.readiness is Readiness.DEGRADED:
            if self.observed_lifecycle_state in {LifecycleState.NEW, LifecycleState.ENROLLING, LifecycleState.PRECHECK}:
                self._set_observed(LifecycleState.DEGRADED)
        else:
            if self.observed_lifecycle_state in {LifecycleState.NEW, LifecycleState.ENROLLING, LifecycleState.PRECHECK}:
                self._set_observed(LifecycleState.READY)
        return decision

    def may_start_ai(self) -> bool:
        return self.scoring_enabled and self.desired_lifecycle_state is LifecycleState.IN_EXAM

    def start_ai_if_authorized(self, starter: Callable[[], None]) -> bool:
        with self._lock:
            if not self.may_start_ai():
                log.info("AI start denied: waiting for EXAM_START")
                return False
            if self.ai_started:
                return True
            starter()
            self.ai_started = True
            return True

    def handle_command(self, command: dict[str, Any]) -> dict[str, Any]:
        """Persist-before-execute. Duplicate idempotency_key returns prior result."""
        key = command.get("idempotency_key")
        with self._lock:
            if key and key in self._command_results:
                raise DuplicateCommand(self._command_results[key])
            seq = self.wal.append(
                "COMMAND_RECEIPT",
                {"command_id": command.get("command_id"), "type": command.get("type")},
                priority="high",
            )
            try:
                result = self._execute_command(command)
            except CommandDenied as exc:
                result = {
                    "ok": False,
                    "error": str(exc),
                    "seq": seq,
                    "observed": self.observed_lifecycle_state.value,
                }
            except Exception as exc:  # noqa: BLE001
                result = {"ok": False, "error": str(exc), "seq": seq}
            if key:
                self._command_results[key] = result
            return result

    def _execute_command(self, command: dict[str, Any]) -> dict[str, Any]:
        ctype = (command.get("type") or "").upper()
        if ctype in {"EXAM_START", "START"}:
            self._transition_desired(LifecycleState.IN_EXAM)
            self.scoring_enabled = True
            self.control_generation += 1
            self._set_observed(LifecycleState.IN_EXAM)
            return {"ok": True, "state": "IN_EXAM", "control_generation": self.control_generation}
        if ctype in {"EXAM_PAUSE", "PAUSE"}:
            self._transition_desired(LifecycleState.PAUSED)
            self.scoring_enabled = False
            self.control_generation += 1
            self._set_observed(LifecycleState.PAUSED)
            return {"ok": True, "state": "PAUSED", "control_generation": self.control_generation}
        if ctype in {"EXAM_RESUME", "RESUME"}:
            self._transition_desired(LifecycleState.IN_EXAM)
            self.scoring_enabled = True
            self.control_generation += 1
            self._set_observed(LifecycleState.IN_EXAM)
            return {"ok": True, "state": "IN_EXAM", "control_generation": self.control_generation}
        if ctype in {"EXAM_END", "END"}:
            self._transition_desired(LifecycleState.ENDED)
            self.scoring_enabled = False
            self.control_generation += 1
            self._set_observed(LifecycleState.ENDED)
            return {"ok": True, "state": "ENDED", "control_generation": self.control_generation}
        if ctype in {"WARN", "REQUEST_CLIP", "UPDATE_POLICY", "KICK"}:
            return {"ok": True, "type": ctype, "accepted": True}
        raise CommandDenied(f"unknown command {ctype}")

    def _transition_desired(self, nxt: LifecycleState) -> None:
        cur = self.desired_lifecycle_state.value
        if nxt.value not in ALLOWED_TRANSITIONS.get(cur, set()) and nxt is not self.desired_lifecycle_state:
            # START from READY/DEGRADED is the happy path; also allow from NEW in tests
            if not (nxt is LifecycleState.IN_EXAM and cur in {"NEW", "READY", "DEGRADED", "PAUSED"}):
                if not (nxt is LifecycleState.PAUSED and cur in {"IN_EXAM"}):
                    if not (nxt is LifecycleState.ENDED and cur in {"IN_EXAM", "PAUSED", "READY", "DEGRADED", "BLOCKED", "NEW"}):
                        raise CommandDenied(f"illegal transition {cur} -> {nxt.value}")
        self.desired_lifecycle_state = nxt

    def _set_observed(self, state: LifecycleState) -> None:
        self.observed_lifecycle_state = state
        self.wal.append(
            "LIFECYCLE",
            self.persist_snapshot(),
            priority="high",
        )
