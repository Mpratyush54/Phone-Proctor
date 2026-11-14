"""Command names and persist-before-execute receiver.

Execution is delegated to ``AgentSupervisor.handle_command`` (receipts by
idempotency key live on the supervisor and in ``agent.storage.command_receipts``).
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

EXAM_START = "EXAM_START"
EXAM_PAUSE = "EXAM_PAUSE"
EXAM_RESUME = "EXAM_RESUME"
EXAM_END = "EXAM_END"
WARN = "WARN"
REQUEST_CLIP = "REQUEST_CLIP"
UPDATE_POLICY = "UPDATE_POLICY"
KICK = "KICK"

KNOWN_COMMANDS = frozenset(
    {
        EXAM_START,
        "START",
        EXAM_PAUSE,
        "PAUSE",
        EXAM_RESUME,
        "RESUME",
        EXAM_END,
        "END",
        WARN,
        REQUEST_CLIP,
        UPDATE_POLICY,
        KICK,
    }
)


class CommandReceiver:
    """Persist-before-execute adapter. Duplicate keys return the prior result."""

    def __init__(self, execute: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        self.execute = execute

    def receive(self, command: Mapping[str, Any]) -> dict[str, Any]:
        from agent.storage.command_receipts import CommandReceiptStore

        if not hasattr(self, "_receipts"):
            self._receipts = CommandReceiptStore()
        key = command.get("idempotency_key")
        if key:
            prior = self._receipts.get(str(key))
            if prior and prior.get("result") is not None:
                return prior["result"]
            # persist receipt before side effects
            self._receipts.put(command, result=None)
        result = self.execute(dict(command))
        if key:
            self._receipts.put(command, result=result)
        return result
