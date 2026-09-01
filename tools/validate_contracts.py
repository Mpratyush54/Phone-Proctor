#!/usr/bin/env python3
"""Validate every contracts/v1 example against its schema (Python)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    import jsonschema
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover
    print("jsonschema is required: pip install jsonschema", file=sys.stderr)
    sys.exit(2)

ROOT = Path(__file__).resolve().parents[1] / "contracts" / "v1"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def validate_examples() -> int:
    errors = 0
    examples = sorted((ROOT / "examples").glob("*.json"))
    if not examples:
        print("no examples found", file=sys.stderr)
        return 1
    registry = json.loads((ROOT / "registries" / "errors.json").read_text(encoding="utf-8"))
    for example in examples:
        schema_name = example.stem.split("__")[0] + ".schema.json"
        schema_path = ROOT / "schemas" / schema_name
        if not schema_path.exists():
            print(f"missing schema for {example.name}: {schema_name}", file=sys.stderr)
            errors += 1
            continue
        schema = load(schema_path)
        instance = load(example)
        validator = Draft202012Validator(schema)
        errs = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
        if errs:
            errors += 1
            print(f"FAIL {example.name}")
            for e in errs:
                print(f"  {list(e.path)}: {e.message}")
        else:
            print(f"OK   {example.name}")
        if instance.get("v") not in (1, None) and instance.get("v") != 1:
            errors += 1
            print(f"FAIL {example.name}: unknown major version")
    print(f"error registry codes: {len(registry['codes'])}")
    return errors


if __name__ == "__main__":
    sys.exit(1 if validate_examples() else 0)
