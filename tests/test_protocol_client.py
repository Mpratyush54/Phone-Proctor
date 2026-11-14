"""C3 credential store + protocol client resume."""

from agent.credential_store import CredentialStore
from agent.protocol_client import ConnectionManager, OrderedSender
from agent.wal import EventWal


def test_save_load_and_strips_enrollment_token(tmp_path):
    store = CredentialStore(tmp_path / "creds.json")
    store.save(
        {
            "device_credential_id": "dev-1",
            "session_id": "sess-1",
            "enrollment_token": "SHOULD_NOT_PERSIST",
            "refresh_token": "rotating",
        }
    )
    loaded = store.load()
    assert loaded["device_credential_id"] == "dev-1"
    assert "enrollment_token" not in loaded
    store.clear()
    assert store.load() is None


def test_ordered_sender_flushes_wal(tmp_path):
    wal = EventWal(tmp_path / "w.sqlite")
    wal.append("METRICS", {"n": 1})
    sent = []
    OrderedSender(wal, lambda env: sent.append(env)).flush()
    assert sent and sent[0]["type"] == "event"
    wal.close()


def test_hello_then_resume_payloads(tmp_path):
    wal = EventWal(tmp_path / "w.sqlite")
    mgr = ConnectionManager(
        "ws://127.0.0.1/agent",
        {"device_credential_id": "d", "session_id": "s"},
        wal,
    )
    hello = mgr.hello_payload()
    resume = mgr.resume_payload(0)
    assert hello["type"] == "hello"
    assert resume["type"] == "resume"
    wal.close()
