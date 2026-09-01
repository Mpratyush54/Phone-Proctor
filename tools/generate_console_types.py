#!/usr/bin/env python3
"""Generate TypeScript types for ConsoleSnapshot and ConsoleDelta from JSON Schema."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts" / "v1"
OUT = ROOT / "admin" / "src" / "generated.ts"


def schema_path(stem: str) -> Path:
    name = f"{stem}.schema.json"
    for path in (CONTRACTS / name, CONTRACTS / "schemas" / name):
        if path.is_file():
            return path
    raise FileNotFoundError(name)


def ts_type(schema: dict, indent: int = 2) -> str:
    if not schema:
        return "unknown"
    if "enum" in schema:
        return " | ".join(json.dumps(v) for v in schema["enum"])
    if "const" in schema:
        return json.dumps(schema["const"])
    t = schema.get("type")
    if isinstance(t, list):
        return " | ".join(ts_type({"type": part}, indent) for part in t)
    if t == "string":
        return "string"
    if t in ("integer", "number"):
        return "number"
    if t == "boolean":
        return "boolean"
    if t == "null":
        return "null"
    if t == "array":
        return f"Array<{ts_type(schema.get('items') or {}, indent)}>"
    if t == "object" or "properties" in schema:
        return object_literal(schema, indent)
    return "unknown"


def object_literal(schema: dict, indent: int) -> str:
    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    pad = " " * indent
    inner = " " * (indent + 2)
    lines = ["{"]
    for name, prop in props.items():
        optional = "?" if name not in required else ""
        lines.append(f"{inner}{name}{optional}: {ts_type(prop, indent + 2)};")
    if schema.get("additionalProperties", True) is not False:
        lines.append(f"{inner}[key: string]: unknown;")
    lines.append(f"{pad}}}")
    return "\n".join(lines)


def emit_interface(title: str, schema: dict) -> str:
    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    lines = [f"export interface {title} {{"]
    for name, prop in props.items():
        optional = "?" if name not in required else ""
        if title == "ConsoleSnapshot" and name == "sessions":
            lines.append(f"  {name}{optional}: ConsoleSession[];")
            continue
        rendered = ts_type(prop, 2)
        lines.append(f"  {name}{optional}: {rendered};")
    if schema.get("additionalProperties", True) is not False:
        lines.append("  [key: string]: unknown;")
    lines.append("}")
    return "\n".join(lines)


def main() -> int:
    snapshot = json.loads(schema_path("console-snapshot").read_text(encoding="utf-8"))
    delta = json.loads(schema_path("console-delta").read_text(encoding="utf-8"))
    session_schema = ((snapshot.get("properties") or {}).get("sessions") or {}).get("items") or {
        "type": "object",
        "properties": {},
    }
    parts = [
        "/**",
        " * Generated from contracts/v1 console JSON Schema.",
        " * Do not edit by hand — run `python tools/generate_console_types.py`.",
        " */",
        "",
        emit_interface("ConsoleSession", session_schema),
        "",
        emit_interface("ConsoleSnapshot", snapshot),
        "",
        emit_interface("ConsoleDelta", delta),
        "",
        "export type ConsoleReadiness = ConsoleSnapshot[\"readiness\"];",
        "export type ConsoleDeltaOp = ConsoleDelta[\"op\"];",
        "",
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(parts), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
