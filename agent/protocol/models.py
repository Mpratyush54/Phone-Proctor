"""Control-plane protocol models aligned with contracts/v1 JSON Schema.

Pydantic v2 is used when installed. Otherwise models are stdlib dataclasses
validated with jsonschema (canonical). PEP 668 environments are not required
to pip-install pydantic.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Literal, Optional

try:
    from pydantic import BaseModel, ConfigDict, ValidationError as PydanticValidationError

    _HAS_PYDANTIC = True
except ImportError:  # pragma: no cover
    _HAS_PYDANTIC = False
    BaseModel = object  # type: ignore[misc, assignment]
    PydanticValidationError = None  # type: ignore[misc, assignment]
    ConfigDict = dict  # type: ignore[misc, assignment]

try:
    from jsonschema import Draft202012Validator

    _HAS_JSONSCHEMA = True
except ImportError:  # pragma: no cover
    Draft202012Validator = None  # type: ignore[misc, assignment]
    _HAS_JSONSCHEMA = False

CONTRACTS_V1 = Path(__file__).resolve().parents[2] / "contracts" / "v1"
PROTOCOL_MAJOR = 1

CommandType = Literal[
    "EXAM_START",
    "EXAM_PAUSE",
    "EXAM_RESUME",
    "EXAM_END",
    "WARN",
    "REQUEST_CLIP",
    "UPDATE_POLICY",
    "KICK",
    "STOP_LIVE",
]


class ProtocolValidationError(ValueError):
    """Raised when a message fails schema or major-version checks."""


def schema_path(stem: str) -> Path:
    """Locate `{stem}.schema.json` in the plan layout, then schemas/, then event-payloads/."""
    name = f"{stem}.schema.json"
    candidates = (
        CONTRACTS_V1 / name,
        CONTRACTS_V1 / "schemas" / name,
        CONTRACTS_V1 / "event-payloads" / name,
    )
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError(f"missing schema {name} (searched {', '.join(str(p) for p in candidates)})")


def load_schema(stem: str) -> dict[str, Any]:
    return json.loads(schema_path(stem).read_text(encoding="utf-8"))


def reject_unknown_major(data: Any) -> None:
    if not isinstance(data, dict):
        return
    if "v" not in data:
        return
    if data["v"] != PROTOCOL_MAJOR:
        raise ProtocolValidationError("unknown major version")


def _minimal_validate(schema: dict[str, Any], instance: Any, path: str = "$") -> None:
    """Fallback validator used only when jsonschema is not installed."""
    if "const" in schema and instance != schema["const"]:
        raise ProtocolValidationError(f"{path}: expected const {schema['const']!r}")
    if "enum" in schema and instance not in schema["enum"]:
        raise ProtocolValidationError(f"{path}: {instance!r} not in enum")
    expected = schema.get("type")
    if expected:
        types = expected if isinstance(expected, list) else [expected]
        ok = False
        for t in types:
            if t == "object" and isinstance(instance, dict):
                ok = True
            elif t == "array" and isinstance(instance, list):
                ok = True
            elif t == "string" and isinstance(instance, str):
                ok = True
            elif t == "integer" and isinstance(instance, int) and not isinstance(instance, bool):
                ok = True
            elif t == "number" and isinstance(instance, (int, float)) and not isinstance(instance, bool):
                ok = True
            elif t == "boolean" and isinstance(instance, bool):
                ok = True
            elif t == "null" and instance is None:
                ok = True
        if not ok:
            raise ProtocolValidationError(f"{path}: expected type {expected}")
    if schema.get("type") == "object" and isinstance(instance, dict):
        for key in schema.get("required") or []:
            if key not in instance:
                raise ProtocolValidationError(f"{path}: missing required {key}")
        props = schema.get("properties") or {}
        additional = schema.get("additionalProperties", True)
        for key, value in instance.items():
            if key in props:
                _minimal_validate(props[key], value, f"{path}.{key}")
            elif additional is False:
                raise ProtocolValidationError(f"{path}: additional property {key}")
            elif isinstance(additional, dict):
                _minimal_validate(additional, value, f"{path}.{key}")
        if "minLength" in schema or "maxLength" in schema:
            pass
    if "minLength" in schema and isinstance(instance, str) and len(instance) < schema["minLength"]:
        raise ProtocolValidationError(f"{path}: minLength")
    if "maxLength" in schema and isinstance(instance, str) and len(instance) > schema["maxLength"]:
        raise ProtocolValidationError(f"{path}: maxLength")
    if "minimum" in schema and isinstance(instance, (int, float)) and instance < schema["minimum"]:
        raise ProtocolValidationError(f"{path}: minimum")
    if "maximum" in schema and isinstance(instance, (int, float)) and instance > schema["maximum"]:
        raise ProtocolValidationError(f"{path}: maximum")
    if schema.get("type") == "array" and isinstance(instance, list):
        item_schema = schema.get("items") or {}
        for i, item in enumerate(instance):
            _minimal_validate(item_schema, item, f"{path}[{i}]")


def validate_contract_instance(stem: str, data: Any) -> None:
    """Validate `data` against the named v1 schema. Rejects unknown majors."""
    reject_unknown_major(data)
    schema = load_schema(stem)
    if _HAS_JSONSCHEMA:
        validator = Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
        if errors:
            first = errors[0]
            raise ProtocolValidationError(f"{stem}: {list(first.path)}: {first.message}") from first
        return
    _minimal_validate(schema, data)


def _fill(cls: type, data: dict[str, Any]) -> Any:
    kwargs: dict[str, Any] = {}
    extras: dict[str, Any] = {}
    field_names = getattr(cls, "__dataclass_fields__", {})
    for key, value in data.items():
        if key in field_names and key != "extra":
            kwargs[key] = value
        else:
            extras[key] = value
    if "extra" in field_names:
        kwargs["extra"] = extras
    return cls(**kwargs)


def _dataclass_validate(cls: type, stem: str, data: Any) -> Any:
    if not isinstance(data, dict):
        raise ProtocolValidationError(f"{stem}: expected object")
    validate_contract_instance(stem, data)
    return _fill(cls, data)


if _HAS_PYDANTIC:

    class _Extra(BaseModel):  # type: ignore[misc, valid-type]
        model_config = ConfigDict(extra="allow")

    class Envelope(_Extra):
        v: Literal[1]
        type: str
        msg_id: str
        ts: str
        session_id: Optional[str] = None
        payload: Optional[dict[str, Any]] = None

        @classmethod
        def model_validate(cls, obj: Any, *args: Any, **kwargs: Any) -> Envelope:  # type: ignore[override]
            reject_unknown_major(obj)
            try:
                return super().model_validate(obj, *args, **kwargs)
            except PydanticValidationError as exc:
                raise ProtocolValidationError(str(exc)) from exc

    class Hello(_Extra):
        v: Literal[1]
        type: Literal["hello"]
        msg_id: str
        ts: str
        payload: dict[str, Any]
        session_id: Optional[str] = None

        @classmethod
        def model_validate(cls, obj: Any, *args: Any, **kwargs: Any) -> Hello:  # type: ignore[override]
            validate_contract_instance("hello", obj)
            try:
                return super().model_validate(obj, *args, **kwargs)
            except PydanticValidationError as exc:
                raise ProtocolValidationError(str(exc)) from exc

    class Resume(_Extra):
        v: Literal[1]
        type: Literal["resume"]
        msg_id: str
        ts: str
        payload: dict[str, Any]
        session_id: Optional[str] = None

        @classmethod
        def model_validate(cls, obj: Any, *args: Any, **kwargs: Any) -> Resume:  # type: ignore[override]
            validate_contract_instance("resume", obj)
            try:
                return super().model_validate(obj, *args, **kwargs)
            except PydanticValidationError as exc:
                raise ProtocolValidationError(str(exc)) from exc

    class Heartbeat(_Extra):
        v: Literal[1]
        type: Literal["heartbeat"]
        msg_id: str
        ts: str
        payload: dict[str, Any]
        session_id: Optional[str] = None

        @classmethod
        def model_validate(cls, obj: Any, *args: Any, **kwargs: Any) -> Heartbeat:  # type: ignore[override]
            validate_contract_instance("heartbeat", obj)
            try:
                return super().model_validate(obj, *args, **kwargs)
            except PydanticValidationError as exc:
                raise ProtocolValidationError(str(exc)) from exc

    class Event(_Extra):
        v: Literal[1]
        type: Literal["event"]
        seq_no: int
        batch_id: str
        payload_hash: str
        payload: dict[str, Any]
        msg_id: Optional[str] = None
        session_id: Optional[str] = None
        ts: Optional[str] = None

        @classmethod
        def model_validate(cls, obj: Any, *args: Any, **kwargs: Any) -> Event:  # type: ignore[override]
            validate_contract_instance("event", obj)
            try:
                return super().model_validate(obj, *args, **kwargs)
            except PydanticValidationError as exc:
                raise ProtocolValidationError(str(exc)) from exc

    class Ack(_Extra):
        v: Literal[1]
        type: Literal["ack"]
        payload: dict[str, Any]
        msg_id: Optional[str] = None
        ts: Optional[str] = None

        @classmethod
        def model_validate(cls, obj: Any, *args: Any, **kwargs: Any) -> Ack:  # type: ignore[override]
            validate_contract_instance("ack", obj)
            try:
                return super().model_validate(obj, *args, **kwargs)
            except PydanticValidationError as exc:
                raise ProtocolValidationError(str(exc)) from exc

    class Nack(_Extra):
        v: Literal[1]
        type: Literal["nack"]
        payload: dict[str, Any]
        msg_id: Optional[str] = None
        ts: Optional[str] = None

        @classmethod
        def model_validate(cls, obj: Any, *args: Any, **kwargs: Any) -> Nack:  # type: ignore[override]
            validate_contract_instance("nack", obj)
            try:
                return super().model_validate(obj, *args, **kwargs)
            except PydanticValidationError as exc:
                raise ProtocolValidationError(str(exc)) from exc

    class Command(_Extra):
        v: Literal[1]
        type: Literal["command"]
        payload: dict[str, Any]
        msg_id: Optional[str] = None
        session_id: Optional[str] = None
        ts: Optional[str] = None

        @classmethod
        def model_validate(cls, obj: Any, *args: Any, **kwargs: Any) -> Command:  # type: ignore[override]
            validate_contract_instance("command", obj)
            try:
                return super().model_validate(obj, *args, **kwargs)
            except PydanticValidationError as exc:
                raise ProtocolValidationError(str(exc)) from exc

    class CommandResult(_Extra):
        v: Literal[1]
        type: Literal["command-result"]
        payload: dict[str, Any]
        msg_id: Optional[str] = None
        ts: Optional[str] = None

        @classmethod
        def model_validate(cls, obj: Any, *args: Any, **kwargs: Any) -> CommandResult:  # type: ignore[override]
            validate_contract_instance("command-result", obj)
            try:
                return super().model_validate(obj, *args, **kwargs)
            except PydanticValidationError as exc:
                raise ProtocolValidationError(str(exc)) from exc

else:

    @dataclass
    class Envelope:
        v: int
        type: str
        msg_id: str
        ts: str
        session_id: Optional[str] = None
        payload: Optional[dict[str, Any]] = None
        extra: dict[str, Any] = field(default_factory=dict)
        _schema_stem: ClassVar[str] = "envelope"

        @classmethod
        def model_validate(cls, obj: Any) -> Envelope:
            return _dataclass_validate(cls, cls._schema_stem, obj)

    @dataclass
    class Hello:
        v: int
        type: str
        msg_id: str
        ts: str
        payload: dict[str, Any]
        session_id: Optional[str] = None
        extra: dict[str, Any] = field(default_factory=dict)
        _schema_stem: ClassVar[str] = "hello"

        @classmethod
        def model_validate(cls, obj: Any) -> Hello:
            return _dataclass_validate(cls, cls._schema_stem, obj)

    @dataclass
    class Resume:
        v: int
        type: str
        msg_id: str
        ts: str
        payload: dict[str, Any]
        session_id: Optional[str] = None
        extra: dict[str, Any] = field(default_factory=dict)
        _schema_stem: ClassVar[str] = "resume"

        @classmethod
        def model_validate(cls, obj: Any) -> Resume:
            return _dataclass_validate(cls, cls._schema_stem, obj)

    @dataclass
    class Heartbeat:
        v: int
        type: str
        msg_id: str
        ts: str
        payload: dict[str, Any]
        session_id: Optional[str] = None
        extra: dict[str, Any] = field(default_factory=dict)
        _schema_stem: ClassVar[str] = "heartbeat"

        @classmethod
        def model_validate(cls, obj: Any) -> Heartbeat:
            return _dataclass_validate(cls, cls._schema_stem, obj)

    @dataclass
    class Event:
        v: int
        type: str
        seq_no: int
        batch_id: str
        payload_hash: str
        payload: dict[str, Any]
        msg_id: Optional[str] = None
        session_id: Optional[str] = None
        ts: Optional[str] = None
        extra: dict[str, Any] = field(default_factory=dict)
        _schema_stem: ClassVar[str] = "event"

        @classmethod
        def model_validate(cls, obj: Any) -> Event:
            return _dataclass_validate(cls, cls._schema_stem, obj)

    @dataclass
    class Ack:
        v: int
        type: str
        payload: dict[str, Any]
        msg_id: Optional[str] = None
        ts: Optional[str] = None
        extra: dict[str, Any] = field(default_factory=dict)
        _schema_stem: ClassVar[str] = "ack"

        @classmethod
        def model_validate(cls, obj: Any) -> Ack:
            return _dataclass_validate(cls, cls._schema_stem, obj)

    @dataclass
    class Nack:
        v: int
        type: str
        payload: dict[str, Any]
        msg_id: Optional[str] = None
        ts: Optional[str] = None
        extra: dict[str, Any] = field(default_factory=dict)
        _schema_stem: ClassVar[str] = "nack"

        @classmethod
        def model_validate(cls, obj: Any) -> Nack:
            return _dataclass_validate(cls, cls._schema_stem, obj)

    @dataclass
    class Command:
        v: int
        type: str
        payload: dict[str, Any]
        msg_id: Optional[str] = None
        session_id: Optional[str] = None
        ts: Optional[str] = None
        extra: dict[str, Any] = field(default_factory=dict)
        _schema_stem: ClassVar[str] = "command"

        @classmethod
        def model_validate(cls, obj: Any) -> Command:
            return _dataclass_validate(cls, cls._schema_stem, obj)

    @dataclass
    class CommandResult:
        v: int
        type: str
        payload: dict[str, Any]
        msg_id: Optional[str] = None
        ts: Optional[str] = None
        extra: dict[str, Any] = field(default_factory=dict)
        _schema_stem: ClassVar[str] = "command-result"

        @classmethod
        def model_validate(cls, obj: Any) -> CommandResult:
            return _dataclass_validate(cls, cls._schema_stem, obj)


PROTOCOL_MODELS: dict[str, Any] = {
    "envelope": Envelope,
    "hello": Hello,
    "resume": Resume,
    "heartbeat": Heartbeat,
    "event": Event,
    "ack": Ack,
    "nack": Nack,
    "command": Command,
    "command-result": CommandResult,
}

__all__ = [
    "Ack",
    "Command",
    "CommandResult",
    "CommandType",
    "CONTRACTS_V1",
    "Envelope",
    "Event",
    "Heartbeat",
    "Hello",
    "Nack",
    "PROTOCOL_MAJOR",
    "PROTOCOL_MODELS",
    "ProtocolValidationError",
    "Resume",
    "load_schema",
    "reject_unknown_major",
    "schema_path",
    "validate_contract_instance",
]
