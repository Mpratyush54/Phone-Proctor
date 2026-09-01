# v1 compatibility

JSON Schema is the canonical protocol definition. Node (AJV) and Python
(Pydantic or jsonschema) validate the same fixtures.

## Major versions

- The envelope field `v` is the **major** protocol version.
- **Unknown majors are rejected** (`SCHEMA_REJECT`). Only `v: 1` is accepted
  for this package.
- A new major is required to remove or rename required fields, change types,
  or tighten enums in a breaking way.

## Within a major version

- **Additive optional fields are compatible.** Receivers must ignore unknown
  properties (`additionalProperties` remains allowed on message objects).
- Required-field additions, type changes, and enum narrowing are breaking and
  are not shipped as v1 patches.

## Registries

Permission strings, error codes, event types, and lifecycle transitions are
versioned contracts under `contracts/v1/registries/`. Applications must not
duplicate them as independent enums.
