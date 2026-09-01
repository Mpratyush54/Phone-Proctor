"""Control-plane protocol client: hello → resume → heartbeats/events."""

from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Any, Callable
from urllib.parse import urlparse

from agent.product_mode import require_wss
from agent.wal import EventWal


class ProtocolError(Exception):
    pass


class ConnectionManager:
    def __init__(self, gateway_url: str, credential: dict[str, Any], wal: EventWal) -> None:
        require_wss(gateway_url)
        self.gateway_url = gateway_url
        self.credential = credential
        self.wal = wal
        self.connected = False
        self.connection_generation = 0
        self._stop = threading.Event()

    def hello_payload(self) -> dict[str, Any]:
        return {
            "v": 1,
            "type": "hello",
            "msg_id": str(uuid.uuid4()),
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "payload": {
                "device_credential_id": self.credential.get("device_credential_id"),
                "session_id": self.credential.get("session_id"),
            },
        }

    def resume_payload(self, last_acked: int) -> dict[str, Any]:
        if "enrollment_token" in self.credential:
            raise ProtocolError("reconnect must use device credential, not enrollment token")
        return {
            "v": 1,
            "type": "resume",
            "msg_id": str(uuid.uuid4()),
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "payload": {
                "device_credential_id": self.credential["device_credential_id"],
                "session_id": self.credential["session_id"],
                "last_acked_seq": last_acked,
                "connection_generation": self.connection_generation,
            },
        }

    def heartbeat_payload(self) -> dict[str, Any]:
        return {
            "v": 1,
            "type": "heartbeat",
            "msg_id": str(uuid.uuid4()),
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "payload": {"rtt_ms": 0},
        }

    def reject_insecure(self) -> None:
        parsed = urlparse(self.gateway_url)
        if parsed.scheme not in {"ws", "wss"}:
            raise ProtocolError("gateway URL must be ws or wss")
        require_wss(self.gateway_url)


class OrderedSender:
    def __init__(self, wal: EventWal, send: Callable[[dict[str, Any]], None]) -> None:
        self.wal = wal
        self.send = send

    def flush(self) -> int:
        n = 0
        for row in self.wal.pending():
            envelope = {
                "v": 1,
                "type": "event",
                "seq_no": row["seq_no"],
                "batch_id": row["batch_id"],
                "payload_hash": row["payload_hash"],
                "payload": json.loads(row["payload_json"]),
            }
            self.send(envelope)
            n += 1
        return n
