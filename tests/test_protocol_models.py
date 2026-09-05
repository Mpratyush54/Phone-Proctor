"""Validate contracts/v1/examples against protocol models (and JSON Schema)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.protocol.models import (
    CONTRACTS_V1,
    PROTOCOL_MODELS,
    ProtocolValidationError,
    Envelope,
    Heartbeat,
    reject_unknown_major,
    validate_contract_instance,
)

EXAMPLES = CONTRACTS_V1 / "examples"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_all_examples_validate_against_schema_and_models():
    files = sorted(EXAMPLES.glob("*.json"))
    assert files, "no contract examples found"
    for path in files:
        stem = path.stem.split("__")[0]
        data = _load(path)
        validate_contract_instance(stem, data)
        model = PROTOCOL_MODELS.get(stem)
        if model is not None:
            parsed = model.model_validate(data)
            assert parsed.v == 1 or stem == "envelope"


def test_unknown_major_rejected():
    with pytest.raises(ProtocolValidationError):
        reject_unknown_major({"v": 2, "type": "heartbeat", "msg_id": "x", "ts": "2026-01-01T00:00:00Z", "payload": {}})
    with pytest.raises(ProtocolValidationError):
        Envelope.model_validate(
            {"v": 2, "type": "heartbeat", "msg_id": "x", "ts": "2026-01-01T00:00:00Z", "payload": {}}
        )


def test_additive_optional_fields_ok():
    msg = {
        "v": 1,
        "type": "heartbeat",
        "msg_id": "x",
        "ts": "2026-01-01T00:00:00Z",
        "payload": {"rtt_ms": 1, "extra_optional": True},
        "future_field": "ok",
    }
    Heartbeat.model_validate(msg)
    validate_contract_instance("heartbeat", msg)
