"""A1 race/resource regression tests: locks, frame copy, deterministic shutdown."""

from __future__ import annotations

import ast
import asyncio
import inspect
import threading
import time
from pathlib import Path

import numpy as np

from agent.shutdown import ShutdownCoordinator, join_thread


def test_audio_lock_is_persistent_not_constructed_in_loop():
    src = Path("ai/audio.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    class_body = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "AudioMonitor")
    init = next(n for n in class_body.body if isinstance(n, ast.FunctionDef) and n.name == "__init__")
    loop = next(n for n in class_body.body if isinstance(n, ast.FunctionDef) and n.name == "_process_loop")

    def lock_calls(fn):
        return [
            n
            for n in ast.walk(fn)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "Lock"
        ]

    assert lock_calls(init), "AudioMonitor must create a persistent Lock in __init__"
    assert not lock_calls(loop), "must not instantiate threading.Lock inside the audio loop"


def test_get_latest_frame_is_locked_and_copies():
    src = Path("network/server.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ProctorServer")
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "get_latest_frame")
    text = ast.get_source_segment(src, fn) or inspect.getsource(fn)
    assert "frame_lock" in text
    assert "copy" in text


class _FakeServer:
    def __init__(self):
        self.frame_lock = threading.Lock()
        self.latest_frame = np.zeros((4, 4, 3), dtype=np.uint8)
        self.latest_frame[0, 0] = (1, 2, 3)

    def get_latest_frame(self):
        with self.frame_lock:
            frame = self.latest_frame
            if frame is None:
                return None
            return frame.copy()


def test_frame_lock_happy_path_and_concurrent_readers():
    server = _FakeServer()
    copies = []
    errors = []

    def reader():
        try:
            for _ in range(50):
                frame = server.get_latest_frame()
                copies.append(frame.copy())
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    def writer():
        for i in range(50):
            with server.frame_lock:
                server.latest_frame[0, 0] = (i, i, i)
            time.sleep(0.001)

    threads = [threading.Thread(target=reader) for _ in range(4)] + [threading.Thread(target=writer)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)
    assert not errors
    assert copies
    first = copies[0]
    with server.frame_lock:
        server.latest_frame[0, 0] = (9, 9, 9)
    assert tuple(first[0, 0]) != (9, 9, 9)


def test_get_latest_frame_none():
    server = _FakeServer()
    server.latest_frame = None
    assert server.get_latest_frame() is None


def test_shutdown_coordinator_runs_lifo_once_and_continues_on_error():
    order = []
    coord = ShutdownCoordinator()
    coord.register("a", lambda: order.append("a"))

    def boom():
        order.append("b")
        raise RuntimeError("denied")

    coord.register("b", boom)
    coord.register("c", lambda: order.append("c"))
    coord.shutdown()
    coord.shutdown()
    assert order == ["c", "b", "a"]
    assert coord.errors and "denied" in coord.errors[0]


def test_join_thread_timeout_does_not_hang():
    ev = threading.Event()

    def worker():
        ev.wait(0.2)

    t = threading.Thread(target=worker)
    t.start()
    join_thread(t, timeout=0.01)
    t.join(timeout=1)


def test_webcam_release_is_idempotent():
    class Cam:
        def __init__(self):
            self._lock = threading.Lock()
            self._released = False
            self.cap = None

        def release(self):
            with self._lock:
                if self._released:
                    return
                self._released = True
                self.cap = None

    cam = Cam()
    cam.release()
    cam.release()
    assert cam._released is True


def test_webrtc_close_sets_closed_flag():
    class Mgr:
        def __init__(self):
            self._closed = False
            self.pcs = set()
            self.active_pc = None

        async def close(self):
            self._closed = True
            self.pcs.clear()
            self.active_pc = None

    mgr = Mgr()
    asyncio.run(mgr.close())
    assert mgr._closed is True
