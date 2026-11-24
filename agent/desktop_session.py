"""Candidate desktop transport for the existing control plane."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from threading import Event
from queue import Empty, SimpleQueue
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID, uuid4

from agent.product_mode import ProductMode, current_mode
from agent.protocol_client import ConnectionManager
from agent.supervisor import AgentSupervisor, DuplicateCommand, LifecycleState
from agent.wal import EventWal

log = logging.getLogger(__name__)
CONTROLS = {"EXAM_START", "EXAM_PAUSE", "EXAM_RESUME", "EXAM_END", "WARN"}
HEARTBEAT_SECONDS = 5
CAMERA_SAMPLE_SECONDS = 10
RETRY_SECONDS = 2


class SessionError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def check_endpoint(address: str, *, websocket: bool) -> str:
    plain, secure = ("ws", "wss") if websocket else ("http", "https")
    address = address.strip()
    try:
        url = urlsplit(address)
        _ = url.port
        if (url.scheme not in (plain, secure) or not url.hostname or url.username is not None
                or url.password is not None or url.fragment or url.query):
            raise ValueError
        if not websocket and url.path not in ("", "/"):
            raise ValueError
    except ValueError as error:
        raise SessionError(f"Enter a valid {'gateway URL' if websocket else 'API address'}.") from error
    if url.scheme == plain and (current_mode() is ProductMode.PRODUCT or url.hostname not in {"localhost", "127.0.0.1", "::1"}):
        raise SessionError(f"Use {secure}:// for a remote connection or in product mode.")
    return address.rstrip("/") if not websocket else address


def exam_link(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        return None
    try:
        link = urlsplit(value)
        _ = link.port
        if not link.hostname or link.username is not None or link.password is not None:
            return None
        loopback = link.hostname in {"localhost", "127.0.0.1", "::1"}
        if link.scheme == "https" or (link.scheme == "http" and loopback and current_mode() is ProductMode.LOCAL):
            return value
    except ValueError:
        return None
    return None


def enroll(api: str, token: str) -> dict[str, Any]:
    if not token.strip():
        raise SessionError("Enter the enrollment token provided by exam staff.")
    request = Request(
        api + "/api/v1/enroll",
        data=json.dumps({"kind": "laptop", "client": "desktop", "token": token.strip()}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with build_opener(NoRedirect()).open(request, timeout=8) as response:
            credential = json.load(response)
        UUID(credential["session_id"])
        UUID(credential["device_credential_id"])
        return credential
    except HTTPError as error:
        if error.code in {400, 401, 403, 409}:
            raise SessionError("Enrollment was declined. Check the token or ask exam staff for a new one.") from error
        raise SessionError(f"The enrollment service returned HTTP {error.code}.") from error
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise SessionError("Could not enroll. Check the API address and the server connection.") from error


class CameraCheck:
    """Samples device availability. Images are neither stored nor sent."""

    def __init__(self, allowed: bool):
        self.allowed = allowed
        self.capture = None

    def sample(self) -> bool:
        if not self.allowed:
            return False
        try:
            if self.capture is None:
                import cv2
                self.capture = cv2.VideoCapture(0)
            available, frame = self.capture.read()
            if available and frame is not None:
                return True
        except Exception:
            log.debug("Camera check failed", exc_info=True)
        self.close()
        return False

    def close(self):
        if self.capture is not None:
            self.capture.release()
            self.capture = None


class DesktopSession:
    def __init__(self, gateway: str, credential: dict[str, Any], wal: EventWal,
                 camera: CameraCheck, publish: Callable[[str, str], None], stop: Event, rechecks: SimpleQueue):
        self.manager = ConnectionManager(gateway, credential, wal)
        self.manager.reject_insecure()
        self.credential = credential
        self.wal = wal
        self.camera = camera
        self.publish = publish
        self.stop = stop
        self.rechecks = rechecks
        self.supervisor = AgentSupervisor(wal)
        self.camera_required = credential.get("camera_required") is True
        self.camera_available: bool | None = None

    def run(self) -> None:
        from websockets.exceptions import ConnectionClosed
        from websockets.sync.client import connect

        while not self.stop.is_set():
            try:
                with connect(self.manager.gateway_url, open_timeout=5, close_timeout=1, max_size=256 * 1024) as socket:
                    self.run_connection(socket)
            except ConnectionClosed as error:
                if error.rcvd and error.rcvd.code in {4400, 4401, 4403, 4409}:
                    raise SessionError("The gateway ended this session. Ask exam staff for a new token.") from error
            except (OSError, TimeoutError):
                pass
            finally:
                self.camera.close()
            if not self.stop.is_set():
                self.publish("connection", "Reconnecting")
                self.publish("camera", "Camera check paused while offline")
                self.stop.wait(RETRY_SECONDS)

    def run_connection(self, socket) -> None:
        def send(message):
            socket.send(json.dumps(message))

        send(self.manager.hello_payload())
        if json.loads(socket.recv(timeout=5)).get("type") != "hello-ok":
            raise SessionError("The address is not a compatible Phone-Proctor gateway.")
        self.check_camera()
        self.camera.close()
        resume = self.manager.resume_payload(self.wal.acked_through())
        resume["payload"]["camera_ready"] = self.camera_available is True
        send(resume)
        resumed = json.loads(socket.recv(timeout=5))
        if resumed.get("type") != "resumed":
            raise SessionError("The gateway did not resume the exam session.")
        self.show_lifecycle(resumed["payload"]["observed_lifecycle_state"])
        self.publish("connection", "Connected")
        self.event("INFO", "Desktop connected")
        next_heartbeat = next_camera = retry_event = 0.0
        in_flight = None
        delayed = False
        while not self.stop.is_set():
            now = time.monotonic()
            try:
                permission = self.rechecks.get_nowait()
            except Empty:
                permission = None
            if permission is not None and self.supervisor.observed_lifecycle_state is not LifecycleState.ENDED:
                self.camera.allowed = permission
                self.check_camera()
                self.camera.close()
                heartbeat = self.manager.heartbeat_payload()
                heartbeat["payload"]["camera_ready"] = self.camera_available is True
                send(heartbeat)
            if now >= next_heartbeat:
                send(self.manager.heartbeat_payload())
                next_heartbeat = now + HEARTBEAT_SECONDS
            if self.camera.allowed and self.supervisor.observed_lifecycle_state is LifecycleState.IN_EXAM and now >= next_camera:
                self.check_camera()
                next_camera = now + CAMERA_SAMPLE_SECONDS
            if now >= retry_event:
                rows = self.wal.pending(limit=1)
                if rows:
                    row = rows[0]
                    in_flight = row["seq_no"]
                    send({"v": 1, "type": "event", "seq_no": in_flight,
                          "batch_id": row["batch_id"], "payload_hash": row["payload_hash"],
                          "payload": json.loads(row["payload_json"])})
                    retry_event = now + 5
            try:
                message = json.loads(socket.recv(timeout=0.25))
            except TimeoutError:
                continue
            payload = message.get("payload") or {}
            if message.get("type") == "command":
                self.on_command(payload, send)
            elif message.get("type") == "heartbeat-ok" and payload.get("observed_lifecycle_state"):
                self.show_lifecycle(payload["observed_lifecycle_state"])
            elif message.get("type") == "ack":
                through = payload.get("acked_through")
                if in_flight is not None and type(through) is int and through >= in_flight:
                    self.wal.ack_through(in_flight)
                    in_flight = None
                    retry_event = 0
                    if delayed:
                        self.publish("connection", "Connected")
                        delayed = False
            elif message.get("type") == "nack" and in_flight == payload.get("seq_no"):
                if payload.get("terminal") or payload.get("code") in {"HASH_MISMATCH", "VALIDATION", "CONFLICT"}:
                    raise SessionError("The server rejected desktop activity. Ask exam staff for help.")
                delayed = True
                self.publish("connection", "Connected · activity delivery delayed")

    def show_lifecycle(self, value: str) -> None:
        state = LifecycleState(value)
        self.supervisor.observed_lifecycle_state = self.supervisor.desired_lifecycle_state = state
        self.publish("lifecycle", state.value)

    def check_camera(self) -> None:
        available = self.camera.sample()
        text = "Camera available" if available else "Camera unavailable" if self.camera.allowed else "Camera check declined"
        self.publish("camera", text)
        if available != self.camera_available:
            self.camera_available = available
            self.event("INFO", text)

    def event(self, event_type: str, detail: str) -> None:
        self.wal.append(event_type, {"event_type": event_type, "detail": detail, "observed_at": time.time()})

    def on_command(self, command, send) -> None:
        command_type = command.get("command_type")
        command_id = command.get("command_id")
        if not isinstance(command_id, str):
            raise SessionError("The gateway sent an invalid exam command.")
        state = self.supervisor.observed_lifecycle_state
        if command_type not in CONTROLS:
            result = {"ok": False}
        else:
            if command_type in {"EXAM_START", "EXAM_RESUME"}:
                self.check_camera()
            if command_type in {"EXAM_START", "EXAM_RESUME"} and self.camera_required and not self.camera_available:
                result = {"ok": False}
                self.publish("notice", "The required webcam is unavailable. Check camera access and try again.")
            else:
                try:
                    result = self.supervisor.handle_command({**command, "type": command_type})
                except DuplicateCommand as duplicate:
                    result = duplicate.prior
        if result.get("ok") and result.get("state"):
            state = LifecycleState(result["state"])
            self.supervisor.observed_lifecycle_state = self.supervisor.desired_lifecycle_state = state
            self.publish("lifecycle", state.value)
        if state is not LifecycleState.IN_EXAM:
            self.camera.close()
        if command_type == "WARN" and result.get("ok"):
            body = command.get("body") or {}
            self.publish("notice", str(body.get("message") or "Exam staff sent you a warning.")[:400])
        self.event("COMMAND_RESULT", f"{command_type}: {'acknowledged' if result.get('ok') else 'declined'}")
        send({"v": 1, "type": "command-result", "msg_id": str(uuid4()), "payload": {
            "command_id": command_id, "ok": result.get("ok") is True, "observed_lifecycle_state": state.value,
        }})


def start_session(api: str, gateway: str, token: str, allow_camera: bool, root: Path,
                  publish: Callable[[str, str], None], stop: Event, rechecks: SimpleQueue) -> None:
    credential = enroll(api, token)
    publish("enrolled", str(credential.get("exam_title") or "Your exam"))
    if link := exam_link(credential.get("exam_url")):
        publish("exam-link", link)
    wal = EventWal(root / "desktop" / credential["session_id"] / "events.sqlite")
    camera = CameraCheck(allow_camera)
    try:
        DesktopSession(gateway, credential, wal, camera, publish, stop, rechecks).run()
    finally:
        camera.close()
        wal.close()
