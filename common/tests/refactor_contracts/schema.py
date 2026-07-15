"""Validation for the versioned canonical refactor scenario envelope."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence


SCENARIO_SCHEMA_VERSION = 1
SUPPORTED_MODES = frozenset({"remote", "loopback", "router", "offline"})
SUPPORTED_ACTOR_KINDS = frozenset({"anonymous", "user", "service"})
SUPPORTED_VOLATILE_KINDS = frozenset({"instant", "uuid", "operation_id", "cursor"})

_REQUIRED_FIELDS = (
    "schemaVersion",
    "scenarioId",
    "capability",
    "mode",
    "actor",
    "input",
    "expected",
    "volatilePaths",
    "unorderedCollections",
)
_ALLOWED_FIELDS = frozenset(_REQUIRED_FIELDS)
_ACTOR_REQUIRED_FIELDS = ("kind", "role", "restaurantRef")
_ACTOR_ALLOWED_FIELDS = frozenset((*_ACTOR_REQUIRED_FIELDS, "subjectRef", "permissionCodes"))
_SCENARIO_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_CAPABILITY_PATTERN = re.compile(r"^CAP-[A-Z0-9]+(?:-[A-Z0-9]+)*$")


class ScenarioContractError(ValueError):
    """Raised when a scenario does not satisfy schema version 1."""


def validate_scenario_v1(value: object) -> dict[str, object]:
    """Validate and return a plain schema-v1 scenario mapping.

    The function deliberately validates only the shared envelope. Capability-owned
    ``input`` and ``expected`` payloads remain opaque mappings.
    """

    scenario = _require_mapping(value, "Scenario contract must be an object.")
    _require_exact_fields(scenario, _REQUIRED_FIELDS, _ALLOWED_FIELDS, "scenario")

    version = scenario["schemaVersion"]
    if type(version) is not int:
        raise ScenarioContractError("Scenario field 'schemaVersion' must be an integer.")
    if version != SCENARIO_SCHEMA_VERSION:
        raise ScenarioContractError(
            f"Unsupported scenario schemaVersion {version}; expected {SCENARIO_SCHEMA_VERSION}."
        )

    _require_pattern(scenario["scenarioId"], "scenarioId", _SCENARIO_ID_PATTERN)
    _require_pattern(scenario["capability"], "capability", _CAPABILITY_PATTERN)

    mode = _require_non_empty_string(scenario["mode"], "mode")
    if mode not in SUPPORTED_MODES:
        raise ScenarioContractError(
            f"Scenario field 'mode' must be one of: {', '.join(sorted(SUPPORTED_MODES))}."
        )

    _validate_actor(scenario["actor"])
    _require_mapping(scenario["input"], "Scenario field 'input' must be an object.")
    _require_mapping(scenario["expected"], "Scenario field 'expected' must be an object.")
    _validate_volatile_paths(scenario["volatilePaths"])
    _validate_unordered_collections(scenario["unorderedCollections"])
    return dict(scenario)


def validate_json_pointer(path: object, *, field: str, wildcard_allowed: bool = True) -> str:
    """Validate the restricted absolute JSON Pointer syntax used by schema v1."""

    pointer = _require_non_empty_string(path, field)
    if not pointer.startswith("/"):
        raise ScenarioContractError(f"Scenario field '{field}' must be an absolute JSON Pointer.")

    segments = pointer[1:].split("/")
    if any(not segment for segment in segments):
        raise ScenarioContractError(f"Scenario field '{field}' contains an empty JSON Pointer segment.")
    for segment in segments:
        if segment == "**" or (segment == "*" and not wildcard_allowed):
            raise ScenarioContractError(f"Scenario field '{field}' contains an unsupported wildcard.")
        _validate_pointer_escapes(segment, field)
    return pointer


def _validate_actor(value: object) -> None:
    actor = _require_mapping(value, "Scenario field 'actor' must be an object.")
    _require_exact_fields(actor, _ACTOR_REQUIRED_FIELDS, _ACTOR_ALLOWED_FIELDS, "actor")

    kind = _require_non_empty_string(actor["kind"], "actor.kind")
    if kind not in SUPPORTED_ACTOR_KINDS:
        raise ScenarioContractError(
            f"Scenario field 'actor.kind' must be one of: {', '.join(sorted(SUPPORTED_ACTOR_KINDS))}."
        )
    _require_non_empty_string(actor["role"], "actor.role")
    _require_non_empty_string(actor["restaurantRef"], "actor.restaurantRef")
    if "subjectRef" in actor:
        _require_non_empty_string(actor["subjectRef"], "actor.subjectRef")
    if "permissionCodes" in actor:
        permissions = _require_sequence(actor["permissionCodes"], "actor.permissionCodes")
        for index, permission in enumerate(permissions):
            _require_non_empty_string(permission, f"actor.permissionCodes[{index}]")


def _validate_volatile_paths(value: object) -> None:
    entries = _require_sequence(value, "volatilePaths")
    seen_paths: set[str] = set()
    for index, raw_entry in enumerate(entries):
        entry = _require_mapping(
            raw_entry,
            f"Scenario field 'volatilePaths[{index}]' must be an object.",
        )
        _require_exact_fields(entry, ("path", "kind"), frozenset({"path", "kind"}), f"volatilePaths[{index}]")
        path = validate_json_pointer(entry["path"], field=f"volatilePaths[{index}].path")
        kind = _require_non_empty_string(entry["kind"], f"volatilePaths[{index}].kind")
        if kind not in SUPPORTED_VOLATILE_KINDS:
            raise ScenarioContractError(
                f"Scenario field 'volatilePaths[{index}].kind' must be one of: "
                f"{', '.join(sorted(SUPPORTED_VOLATILE_KINDS))}."
            )
        _reject_duplicate_path(path, seen_paths, "volatilePaths")


def _validate_unordered_collections(value: object) -> None:
    entries = _require_sequence(value, "unorderedCollections")
    seen_paths: set[str] = set()
    for index, raw_entry in enumerate(entries):
        entry = _require_mapping(
            raw_entry,
            f"Scenario field 'unorderedCollections[{index}]' must be an object.",
        )
        _require_exact_fields(
            entry,
            ("path", "keys"),
            frozenset({"path", "keys"}),
            f"unorderedCollections[{index}]",
        )
        path = validate_json_pointer(entry["path"], field=f"unorderedCollections[{index}].path")
        _reject_duplicate_path(path, seen_paths, "unorderedCollections")
        keys = _require_sequence(entry["keys"], f"unorderedCollections[{index}].keys")
        if not keys:
            raise ScenarioContractError(
                f"Scenario field 'unorderedCollections[{index}].keys' must not be empty."
            )
        seen_keys: set[str] = set()
        for key_index, raw_key in enumerate(keys):
            key = validate_json_pointer(
                raw_key,
                field=f"unorderedCollections[{index}].keys[{key_index}]",
                wildcard_allowed=False,
            )
            _reject_duplicate_path(key, seen_keys, f"unorderedCollections[{index}].keys")


def _require_exact_fields(
    value: Mapping[object, object],
    required: Sequence[str],
    allowed: frozenset[str],
    field: str,
) -> None:
    for name in required:
        if name not in value:
            raise ScenarioContractError(f"Scenario field '{field}.{name}' is required.")
    unknown = sorted(str(name) for name in value if name not in allowed)
    if unknown:
        raise ScenarioContractError(
            f"Scenario field '{field}' contains unsupported fields: {', '.join(unknown)}."
        )


def _require_mapping(value: object, message: str) -> Mapping[object, object]:
    if not isinstance(value, Mapping):
        raise ScenarioContractError(message)
    return value


def _require_sequence(value: object, field: str) -> Sequence[object]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ScenarioContractError(f"Scenario field '{field}' must be an array.")
    return value


def _require_non_empty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ScenarioContractError(f"Scenario field '{field}' must be a non-empty string.")
    return value


def _require_pattern(value: object, field: str, pattern: re.Pattern[str]) -> None:
    text = _require_non_empty_string(value, field)
    if pattern.fullmatch(text) is None:
        raise ScenarioContractError(f"Scenario field '{field}' has an invalid format.")


def _validate_pointer_escapes(segment: str, field: str) -> None:
    index = 0
    while index < len(segment):
        if segment[index] != "~":
            index += 1
            continue
        if index + 1 >= len(segment) or segment[index + 1] not in {"0", "1"}:
            raise ScenarioContractError(f"Scenario field '{field}' contains an invalid JSON Pointer escape.")
        index += 2


def _reject_duplicate_path(path: str, seen: set[str], field: str) -> None:
    if path in seen:
        raise ScenarioContractError(f"Scenario field '{field}' contains duplicate path '{path}'.")
    seen.add(path)
