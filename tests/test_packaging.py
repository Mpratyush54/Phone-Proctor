"""A5 packaging: frozen smoke, signed release, update, rollback."""

import json
from pathlib import Path

import pytest

from agent.packaging import build_manifest, install_release, rollback_release, verify_manifest, write_manifest


def test_manifest_not_bootstrapped_at_runtime(tmp_path):
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "agent").write_text("ok", encoding="utf-8")
    dest = tmp_path / "integrity-manifest.json"
    write_manifest(dest=dest, root=tmp_path / "bin")
    data = json.loads(dest.read_text(encoding="utf-8"))
    assert data["built_at_boot"] is False
    assert "agent" in data["files"]
    assert verify_manifest(dest, root=tmp_path / "bin") == []


def test_manifest_detects_mismatch_and_missing(tmp_path):
    root = tmp_path / "pkg"
    root.mkdir()
    (root / "a.txt").write_text("one", encoding="utf-8")
    dest = tmp_path / "m.json"
    write_manifest(dest=dest, root=root)
    (root / "a.txt").write_text("two", encoding="utf-8")
    (root / "b.txt").write_text("new", encoding="utf-8")
    errors = verify_manifest(dest, root=root)
    assert any(e.startswith("mismatch:") for e in errors)
    (root / "a.txt").unlink()
    errors = verify_manifest(dest, root=root)
    assert any(e.startswith("missing:") for e in errors)


def test_reject_bootstrapped_manifest(tmp_path):
    root = tmp_path / "pkg"
    root.mkdir()
    (root / "x").write_text("x", encoding="utf-8")
    dest = tmp_path / "m.json"
    dest.write_text(json.dumps({"built_at_boot": True, "files": {}}), encoding="utf-8")
    with pytest.raises(ValueError):
        verify_manifest(dest, root=root)


def test_install_update_and_rollback(tmp_path):
    v1 = tmp_path / "v1"
    v2 = tmp_path / "v2"
    current = tmp_path / "current"
    v1.mkdir()
    v2.mkdir()
    (v1 / "app").write_text("1", encoding="utf-8")
    (v2 / "app").write_text("2", encoding="utf-8")
    install_release(v1, current)
    assert (current / "app").read_text() == "1"
    install_release(v2, current)
    assert (current / "app").read_text() == "2"
    rollback_release(current, v1)
    assert (current / "app").read_text() == "1"


def test_signed_release_hmac(tmp_path):
    root = tmp_path / "pkg"
    root.mkdir()
    (root / "app").write_text("bin", encoding="utf-8")
    dest = tmp_path / "integrity-manifest.json"
    write_manifest(dest=dest, root=root)
    from agent.packaging import sign_manifest, verify_signature
    key = b"release-key"
    sign_manifest(dest, key)
    assert verify_signature(dest, key) is True
    dest.write_text(dest.read_text() + " ", encoding="utf-8")
    assert verify_signature(dest, key) is False


def test_rollback_without_previous_denied(tmp_path):
    with pytest.raises(FileNotFoundError):
        rollback_release(tmp_path / "cur", tmp_path / "missing")
