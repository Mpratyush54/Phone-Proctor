"""A3 product-mode security tests."""

from pathlib import Path

import pytest

from agent.product_mode import current_mode, google_stt_enabled, lan_bind_host, require_wss, ProductMode
from agent.protocol_client import ConnectionManager, ProtocolError
from agent.wal import EventWal
from network.tcp_server import TCPServer
from network.server_discovery import DiscoveryServer


def test_cmd_kill_does_not_terminate():
    src = Path("screen/safe_browser.py").read_text(encoding="utf-8")
    assert "proc.terminate" not in src
    assert "CMD:KILL ignored" in src


def test_escape_does_not_close_exam():
    src = Path("screen/safe_browser.py").read_text(encoding="utf-8")
    # keyPressEvent must not call self.close() on Escape
    assert "Escape ignored" in src
    assert "self.close()" not in src.split("def keyPressEvent")[1].split("def closeEvent")[0]


def test_product_mode_requires_wss(monkeypatch):
    monkeypatch.setenv("PHONE_PROCTOR_MODE", "product")
    assert current_mode() is ProductMode.PRODUCT
    with pytest.raises(PermissionError):
        require_wss("ws://localhost:8080/agent")
    require_wss("wss://gateway.example/agent")


def test_google_stt_disabled_in_product(monkeypatch):
    monkeypatch.setenv("PHONE_PROCTOR_MODE", "product")
    monkeypatch.setenv("PHONE_PROCTOR_GOOGLE_STT", "1")
    assert google_stt_enabled() is False


def test_google_stt_off_by_default_in_local(monkeypatch):
    monkeypatch.delenv("PHONE_PROCTOR_MODE", raising=False)
    monkeypatch.delenv("PHONE_PROCTOR_GOOGLE_STT", raising=False)
    assert google_stt_enabled() is False


def test_product_lan_binds_localhost(monkeypatch):
    monkeypatch.setenv("PHONE_PROCTOR_MODE", "product")
    assert lan_bind_host() == "127.0.0.1"
    tcp = TCPServer(port=0, callback=None)
    assert tcp.host == "127.0.0.1"
    disc = DiscoveryServer()
    assert disc.bind_host == "127.0.0.1"


def test_reconnect_denies_enrollment_token(tmp_path, monkeypatch):
    monkeypatch.setenv("PHONE_PROCTOR_MODE", "local")
    wal = EventWal(tmp_path / "wal.sqlite")
    mgr = ConnectionManager("ws://127.0.0.1:1/agent", {"enrollment_token": "x"}, wal)
    with pytest.raises(ProtocolError):
        mgr.resume_payload(0)
    wal.close()
