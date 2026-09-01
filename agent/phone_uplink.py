"""E6 phone heartbeat + snapshot using pairing credential. LAN disabled in product."""

from __future__ import annotations

import time
from typing import Any

from agent.product_mode import ProductMode, current_mode


class PhoneUplink:
    def __init__(self, credential: dict[str, Any], lan_enabled: bool = False) -> None:
        if credential.get("can_register_agent"):
            raise PermissionError("pairing credential cannot register an agent")
        self.credential = credential
        self.lan_enabled = lan_enabled and current_mode() is not ProductMode.PRODUCT
        self.last_heartbeat = 0.0

    def heartbeat(self, now: float | None = None) -> dict[str, Any]:
        self.last_heartbeat = now if now is not None else time.time()
        return {
            "type": "heartbeat",
            "device_credential_id": self.credential["device_credential_id"],
            "session_id": self.credential["session_id"],
            "lan": self.lan_enabled,
        }

    def snapshot_meta(self, sha256: str, bytes_n: int) -> dict[str, Any]:
        return {
            "kind": "snapshot",
            "sha256": sha256,
            "bytes": bytes_n,
            "device_credential_id": self.credential["device_credential_id"],
        }
