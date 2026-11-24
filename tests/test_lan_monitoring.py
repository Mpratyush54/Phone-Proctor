import asyncio
import base64
import json
import threading

import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")
websockets = pytest.importorskip("websockets")
pytest.importorskip("aiortc")

from network.server import ProctorServer


async def wait_until(check):
    async def poll():
        while not check():
            await asyncio.sleep(0.01)

    await asyncio.wait_for(poll(), timeout=3)


def image_message(camera):
    ok, encoded = cv2.imencode(".jpg", np.full((24, 32, 3), 128, dtype=np.uint8))
    assert ok
    return json.dumps({
        "type": "VIDEO_FRAME",
        "data": {"camera": camera, "image": base64.b64encode(encoded).decode("ascii")},
    })


def test_replacement_owns_monitoring_and_disconnect_clears_samples(monkeypatch):
    server = ProctorServer(host="127.0.0.1")
    late_decode_started = threading.Event()
    allow_late_decode = threading.Event()
    late_decode_finished = threading.Event()
    original_decode = server._decode_frame

    def decode(websocket, data):
        if data["camera"] == "back":
            late_decode_started.set()
            assert allow_late_decode.wait(5)
            original_decode(websocket, data)
            late_decode_finished.set()
            return
        original_decode(websocket, data)

    monkeypatch.setattr(server, "_decode_frame", decode)

    async def scenario():
        async with websockets.serve(server._handle_client, "127.0.0.1", 0) as listener:
            address = f"ws://127.0.0.1:{listener.sockets[0].getsockname()[1]}"
            async with websockets.connect(address) as old:
                await old.send(image_message("front"))
                await old.send('{"type":"TELEMETRY","data":{"audioLevel":0.5}}')
                await wait_until(lambda: server.get_status()["phone_audio"] == 0.5)
                assert server.get_status()["camera"] == "front"
                assert server.get_latest_frame().shape == (24, 32, 3)

                await old.send(image_message("back"))
                await wait_until(late_decode_started.is_set)
                try:
                    async with websockets.connect(address) as current:
                        await asyncio.wait_for(old.wait_closed(), timeout=3)
                        assert server.get_status()["connected"]
                        assert server.get_status()["latest_telemetry"] == {}
                        assert server.get_status()["phone_audio"] == 0
                        assert server.get_latest_frame() is None

                        allow_late_decode.set()
                        await wait_until(late_decode_finished.is_set)
                        assert server.get_status()["camera"] is None
                        assert server.get_latest_frame() is None

                        await current.send(image_message("front"))
                        await current.send('{"type":"TELEMETRY","data":{"audioLevel":0.25}}')
                        await wait_until(lambda: server.get_status()["phone_audio"] == 0.25)
                        assert server.get_status()["connected"]
                        assert server.get_status()["camera"] == "front"
                        assert await server.send_command("SET_CAMERA", {"camera": "back"})
                        assert json.loads(await asyncio.wait_for(current.recv(), timeout=3))["type"] == "SET_CAMERA"
                    await wait_until(lambda: not server.get_status()["connected"])
                    assert server.get_latest_frame() is None
                    assert server.get_status()["camera"] is None
                    assert server.get_status()["phone_audio"] == 0
                    assert server.get_status()["latest_telemetry"] == {}
                finally:
                    allow_late_decode.set()

    asyncio.run(scenario())
