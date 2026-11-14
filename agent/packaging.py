"""Signed frozen packaging: integrity manifest at build time, update/rollback."""

from __future__ import annotations

import hmac
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from utils.paths import install_root, integrity_manifest_path


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(root: Path | None = None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    root = root or install_root()
    files = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name in {"integrity-manifest.json", "integrity-manifest.json.sig"}:
            continue
        rel = str(path.relative_to(root)).replace("\\", "/")
        files[rel] = file_sha256(path)
    manifest = {
        "schema": 1,
        "built_at_boot": False,
        "files": files,
        **(extra or {}),
    }
    return manifest


def write_manifest(dest: Path | None = None, root: Path | None = None) -> Path:
    dest = dest or integrity_manifest_path()
    manifest = build_manifest(root=root)
    dest.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return dest


def verify_manifest(manifest_path: Path | None = None, root: Path | None = None) -> list[str]:
    manifest_path = manifest_path or integrity_manifest_path()
    root = root or install_root()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if data.get("built_at_boot"):
        raise ValueError("integrity manifest must be shipped at build time, not bootstrapped")
    errors = []
    for rel, expected in data.get("files", {}).items():
        path = root / rel
        if not path.exists():
            errors.append(f"missing:{rel}")
            continue
        if file_sha256(path) != expected:
            errors.append(f"mismatch:{rel}")
    return errors


def install_release(src: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest, dirs_exist_ok=True)


def rollback_release(current: Path, previous: Path) -> None:
    if not previous.exists():
        raise FileNotFoundError("no previous release to roll back to")
    backup = current.with_name(current.name + ".failed")
    if current.exists():
        if backup.exists():
            shutil.rmtree(backup)
        current.rename(backup)
    shutil.copytree(previous, current)


def sign_manifest(manifest_path: Path, key: bytes) -> Path:
    body = manifest_path.read_bytes()
    sig = hmac.new(key, body, hashlib.sha256).hexdigest()
    dest = manifest_path.with_suffix(manifest_path.suffix + ".sig")
    dest.write_text(sig, encoding="utf-8")
    return dest


def verify_signature(manifest_path: Path, key: bytes) -> bool:
    sig_path = manifest_path.with_suffix(manifest_path.suffix + ".sig")
    if not sig_path.exists():
        raise FileNotFoundError("missing signature")
    expected = hmac.new(key, manifest_path.read_bytes(), hashlib.sha256).hexdigest()
    got = sig_path.read_text(encoding="utf-8").strip()
    return hmac.compare_digest(expected, got)
