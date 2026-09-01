"""Product bootstrap layout: supervisor construction, WSS guard, student shell."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

from agent.bootstrap import build_runtime, main, parse_args
from agent.health import health_status
from agent.policy import apply_gateway_policy
from agent.supervisor import AgentSupervisor
from screen.student_shell import StudentShell

NEW_MODULES = [
    Path("agent/bootstrap.py"),
    Path("agent/config.py"),
    Path("agent/health.py"),
    Path("agent/policy.py"),
    Path("agent/protocol/__init__.py"),
    Path("agent/protocol/client.py"),
    Path("agent/protocol/commands.py"),
    Path("agent/storage/__init__.py"),
    Path("agent/storage/event_wal.py"),
    Path("agent/storage/command_receipts.py"),
    Path("agent/storage/media_spool.py"),
    Path("agent/media/__init__.py"),
    Path("agent/media/snapshots.py"),
    Path("agent/media/ring_buffer.py"),
    Path("agent/media/livekit_publisher.py"),
    Path("screen/student_shell.py"),
]

FORBIDDEN_IMPORTS = {"cv2", "sklearn", "utils.logger"}


def _imported_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
            names.add(node.module)
    return names


def test_new_modules_do_not_import_cv2_sklearn_or_utils_logger():
    for path in NEW_MODULES:
        names = _imported_names(path)
        bad = names & FORBIDDEN_IMPORTS
        assert not bad, f"{path} imports {bad}"


def test_bootstrap_constructs_supervisor(tmp_path, monkeypatch):
    monkeypatch.setenv("PHONE_PROCTOR_MODE", "local")
    args = parse_args(["--mode", "local", "--gateway", "ws://127.0.0.1/agent", "--enroll-token", "tok"])
    runtime = build_runtime(args, wal_path=tmp_path / "w.sqlite")
    try:
        assert isinstance(runtime.supervisor, AgentSupervisor)
        assert runtime.supervisor.may_start_ai() is False
        assert runtime.consent_gate is runtime.supervisor.gate
        assert runtime.enroll_token == "tok"
        started: list[int] = []
        assert runtime.supervisor.start_ai_if_authorized(lambda: started.append(1)) is False
        assert started == []
        status = health_status(wal=runtime.wal, data_root=tmp_path)
        assert "disk" in status and "wal" in status and "spool" in status
        assert status["wal"]["present"] is True
    finally:
        runtime.close()


def test_product_mode_rejects_ws(tmp_path, monkeypatch):
    monkeypatch.setenv("PHONE_PROCTOR_MODE", "product")
    with pytest.raises(PermissionError):
        apply_gateway_policy("ws://insecure.example/agent")
    args = parse_args(["--mode", "product", "--gateway", "ws://insecure.example/agent"])
    with pytest.raises(PermissionError):
        build_runtime(args, wal_path=tmp_path / "w.sqlite")
    ok = parse_args(["--mode", "product", "--gateway", "wss://gateway.example/agent"])
    runtime = build_runtime(ok, wal_path=tmp_path / "w.sqlite")
    try:
        assert runtime.supervisor.may_start_ai() is False
        assert runtime.gateway.startswith("wss://")
    finally:
        runtime.close()


def test_student_shell_records_lifecycle(capsys):
    shell = StudentShell()
    shell.set_lifecycle("READY")
    shell.set_lifecycle("IN_EXAM")
    assert shell.lifecycle == "IN_EXAM"
    assert shell.events == ["READY", "IN_EXAM"]
    out = capsys.readouterr().out
    assert "READY" in out and "IN_EXAM" in out


def test_bootstrap_main_importable_without_cv2(tmp_path, monkeypatch):
    monkeypatch.setenv("PHONE_PROCTOR_MODE", "product")
    monkeypatch.setenv("PHONE_PROCTOR_DATA_DIR", str(tmp_path))
    assert callable(main)
    runtime = main(
        ["--mode", "product", "--gateway", "wss://gateway.example/agent"],
        wal_path=tmp_path / "w.sqlite",
        run_legacy=False,
    )
    try:
        assert runtime.supervisor.may_start_ai() is False
    finally:
        runtime.close()


def test_persist_before_execute_returns_prior_result():
    from agent.protocol.commands import CommandReceiver

    calls: list = []

    def execute(c):
        calls.append(c)
        return {"ok": True, "n": len(calls)}

    recv = CommandReceiver(execute)
    a = recv.receive({"type": "WARN", "idempotency_key": "k"})
    b = recv.receive({"type": "WARN", "idempotency_key": "k"})
    assert a == b
    assert len(calls) == 1


def test_python_c_from_agent_bootstrap_import_main():
    import os
    import subprocess

    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(".").resolve())
    result = subprocess.run(
        [sys.executable, "-c", "from agent.bootstrap import main"],
        cwd=str(Path(".").resolve()),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr
