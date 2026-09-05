"""
Agent uplink client → central Node server (WSS).

Sends JSON control/events; binary frames later. Replays unacked journal batches.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Any, Callable, Dict, Optional

from agent.journal import WriteAheadJournal
from pp_platform import Heartbeat, device_fingerprint, verify_against_manifest


class AgentUplink:
    def __init__(
        self,
        server_url: str,
        session_id: str,
        journal: Optional[WriteAheadJournal] = None,
        exam_code: str = "",
        student_id: str = "",
        on_command: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        self.server_url = server_url.rstrip("/")
        self.ws_url = self._to_ws_url(server_url)
        self.session_id = session_id
        self.exam_code = exam_code
        self.student_id = student_id
        self.journal = journal or WriteAheadJournal(session_id)
        self.on_command = on_command
        self.heartbeat = Heartbeat()

        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ws = None
        self._running = False
        self._send_queue: asyncio.Queue = None  # type: ignore

    @staticmethod
    def _to_ws_url(url: str) -> str:
        if url.startswith("wss://") or url.startswith("ws://"):
            return url
        if url.startswith("https://"):
            return "wss://" + url[len("https://") :]
        if url.startswith("http://"):
            return "ws://" + url[len("http://") :]
        return "ws://" + url

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="AgentUplink")
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(lambda: None)
        if self._thread:
            self._thread.join(timeout=3)

    def emit(self, event_type: str, data: Optional[Dict[str, Any]] = None) -> None:
        batch = self.journal.append(event_type, data)
        self._enqueue({"op": "batch", "batch": batch.to_dict()})

    def _enqueue(self, msg: Dict[str, Any]) -> None:
        if not self._loop or not self._send_queue:
            return
        def _put():
            try:
                self._send_queue.put_nowait(msg)
            except Exception:
                pass
        self._loop.call_soon_threadsafe(_put)

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._main())

    async def _main(self) -> None:
        self._send_queue = asyncio.Queue()
        while self._running:
            try:
                await self._session()
            except Exception as e:
                print(f"[UPLINK] session error: {e}")
            if self._running:
                await asyncio.sleep(2)

    async def _session(self) -> None:
        try:
            import websockets
        except ImportError as e:
            raise RuntimeError("websockets package required for uplink") from e

        print(f"[UPLINK] Connecting {self.ws_url} ...")
        async with websockets.connect(self.ws_url, max_size=10_000_000) as ws:
            self._ws = ws
            await self._register(ws)
            await self._replay_unacked(ws)

            hb_task = asyncio.create_task(self._heartbeat_loop(ws))
            writer = asyncio.create_task(self._writer_loop(ws))
            reader = asyncio.create_task(self._reader_loop(ws))
            try:
                await asyncio.wait(
                    [hb_task, writer, reader],
                    return_when=asyncio.FIRST_EXCEPTION,
                )
            finally:
                for t in (hb_task, writer, reader):
                    t.cancel()
                self._ws = None

    async def _register(self, ws) -> None:
        integrity = verify_against_manifest()
        msg = {
            "op": "register",
            "session_id": self.session_id,
            "exam_code": self.exam_code,
            "student_id": self.student_id,
            "fingerprint": device_fingerprint(),
            "integrity": {
                "status": integrity.get("status"),
                "ok": integrity.get("ok"),
                "mismatches": integrity.get("mismatches"),
                "missing": integrity.get("missing"),
            },
            "ts": time.time(),
        }
        await ws.send(json.dumps(msg))
        if integrity.get("status") == "TAMPERED":
            print("[UPLINK] WARNING: integrity TAMPERED — flagged to server")

    async def _replay_unacked(self, ws) -> None:
        pending = self.journal.iter_unacked()
        if not pending:
            return
        print(f"[UPLINK] Replaying {len(pending)} unacked batches")
        for batch in pending:
            await ws.send(json.dumps({"op": "batch", "batch": batch.to_dict()}))

    async def _heartbeat_loop(self, ws) -> None:
        while self._running:
            payload = {"op": "heartbeat", "session_id": self.session_id, **self.heartbeat.tick()}
            await ws.send(json.dumps(payload))
            await asyncio.sleep(5)

    async def _writer_loop(self, ws) -> None:
        while self._running:
            msg = await self._send_queue.get()
            await ws.send(json.dumps(msg))

    async def _reader_loop(self, ws) -> None:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            op = msg.get("op")
            if op == "ack":
                ids = msg.get("batch_ids") or []
                if ids:
                    self.journal.ack(ids)
                    self.journal.compact_acked()
            elif op == "command" and self.on_command:
                try:
                    self.on_command(msg.get("data") or {})
                except Exception as e:
                    print(f"[UPLINK] command handler error: {e}")
