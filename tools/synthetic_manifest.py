"""F5: scenario manifest, truth split, and hash-addressed .done cache."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def lock_hash(config: dict[str, Any], code_version: str = "1") -> str:
    blob = json.dumps({"config": config, "code": code_version}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def write_scenario_manifest(
    out_dir: str | Path,
    *,
    seeds: dict[str, int],
    domains: dict[str, Any],
    observable_truth: dict[str, Any],
    pair_id: str | None,
    config: dict[str, Any],
    code_version: str = "1",
) -> dict[str, Any]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    manifest = {
        "seeds": seeds,
        "domains": domains,
        "observable_truth": observable_truth,
        "pair_id": pair_id,
        "config": config,
        "code_version": code_version,
        "lock_hash": lock_hash(config, code_version),
    }
    (out / "scenario_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (out / "latent_truth.jsonl").write_text(json.dumps(observable_truth) + "\n", encoding="utf-8")
    return manifest


def write_done(out_dir: str | Path, lock: str) -> None:
    Path(out_dir, ".done").write_text(lock, encoding="utf-8")


def done_matches(out_dir: str | Path, lock: str) -> bool:
    path = Path(out_dir, ".done")
    if not path.is_file():
        return False
    return path.read_text(encoding="utf-8").strip() == lock
