"""Durable command receipts keyed by idempotency key.

Wraps ``AgentSupervisor`` in-memory receipts when a supervisor is supplied.
Duplicate delivery returns the stored result.
"""

from __future__ import annotations

import time
from typing import Any, Mapping


class CommandReceiptStore:
    def __init__(self, supervisor: Any | None = None) -> None:
        self._supervisor = supervisor
        self._receipts: dict[str, dict[str, Any]] = {}

    def wrap_supervisor(self, supervisor: Any) -> CommandReceiptStore:
        self._supervisor = supervisor
        return self

    def _supervisor_map(self) -> dict[str, dict[str, Any]] | None:
        if self._supervisor is None:
            return None
        stored = getattr(self._supervisor, "_command_results", None)
        return stored if isinstance(stored, dict) else None

    def get(self, idempotency_key: str) -> dict[str, Any] | None:
        key = str(idempotency_key)
        local = self._receipts.get(key)
        if local is not None:
            return local
        mapped = self._supervisor_map()
        if mapped is not None and key in mapped:
            return {
                "idempotency_key": key,
                "result": mapped[key],
                "source": "supervisor",
            }
        return None

    def put(
        self,
        command: Mapping[str, Any],
        result: dict[str, Any] | None = None,
        *,
        received_at: float | None = None,
    ) -> dict[str, Any]:
        key = command.get("idempotency_key")
        receipt = {
            "idempotency_key": key,
            "command": dict(command),
            "result": result,
            "received_at": received_at if received_at is not None else time.time(),
        }
        if key:
            self._receipts[str(key)] = receipt
            mapped = self._supervisor_map()
            if mapped is not None and result is not None:
                mapped.setdefault(str(key), result)
        return receipt

    def record_from_supervisor(self, command: Mapping[str, Any]) -> dict[str, Any]:
        """Execute via supervisor.handle_command and store the receipt."""
        if self._supervisor is None:
            raise RuntimeError("no supervisor wrapped")
        result = self._supervisor.handle_command(dict(command))
        return self.put(command, result)
