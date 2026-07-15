"""Pure, allowlist-only normalization for canonical refactor scenarios."""

from __future__ import annotations

import math
import uuid
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from .schema import ScenarioContractError, validate_scenario_v1


@dataclass(frozen=True)
class _Match:
    parent: dict[str, object] | list[object]
    key: str | int

    @property
    def value(self) -> object:
        return self.parent[self.key]  # type: ignore[index]

    def replace(self, value: object) -> None:
        self.parent[self.key] = value  # type: ignore[index]

    @property
    def identity(self) -> tuple[int, str | int]:
        return id(self.parent), self.key


def normalize_scenario_expected(scenario: object) -> dict[str, object]:
    """Return a normalized deep copy of a validated scenario's expected outcome."""

    validated = validate_scenario_v1(scenario)
    expected = cast(dict[str, object], validated["expected"])
    normalized = deepcopy(expected)

    _apply_ordering_rules(normalized, cast(list[object], validated["unorderedCollections"]))
    _apply_volatile_paths(normalized, cast(list[object], validated["volatilePaths"]))
    return normalized


def _apply_ordering_rules(root: dict[str, object], raw_rules: list[object]) -> None:
    sorted_targets: set[tuple[int, str | int]] = set()
    for index, raw_rule in enumerate(raw_rules):
        rule = cast(dict[str, object], raw_rule)
        path = cast(str, rule["path"])
        keys = cast(list[str], rule["keys"])
        for match in _resolve_matches(root, path, field=f"unorderedCollections[{index}].path"):
            if match.identity in sorted_targets:
                raise ScenarioContractError(f"Normalization target '{path}' is declared more than once.")
            sorted_targets.add(match.identity)
            collection = match.value
            if not isinstance(collection, list):
                raise ScenarioContractError(f"Normalization target '{path}' must resolve to an array.")
            collection.sort(key=lambda item: _collection_sort_key(item, keys, path))


def _apply_volatile_paths(root: dict[str, object], raw_rules: list[object]) -> None:
    tokens: dict[str, dict[str, str]] = {
        "instant": {},
        "uuid": {},
        "operation_id": {},
        "cursor": {},
    }
    tokenized_targets: set[tuple[int, str | int]] = set()
    for index, raw_rule in enumerate(raw_rules):
        rule = cast(dict[str, object], raw_rule)
        path = cast(str, rule["path"])
        kind = cast(str, rule["kind"])
        for match in _resolve_matches(root, path, field=f"volatilePaths[{index}].path"):
            if match.identity in tokenized_targets:
                raise ScenarioContractError(f"Normalization target '{path}' is declared more than once.")
            tokenized_targets.add(match.identity)
            raw_value = _validate_volatile_scalar(match.value, kind, path)
            kind_tokens = tokens[kind]
            token = kind_tokens.get(raw_value)
            if token is None:
                token = f"<{kind}:{len(kind_tokens) + 1}>"
                kind_tokens[raw_value] = token
            match.replace(token)


def _resolve_matches(root: object, pointer: str, *, field: str) -> list[_Match]:
    current: list[object] = [root]
    matches: list[_Match] = []
    segments = [_decode_pointer_segment(segment) for segment in pointer[1:].split("/")]

    for segment_index, segment in enumerate(segments):
        is_last = segment_index == len(segments) - 1
        next_nodes: list[object] = []
        matches = []
        for node in current:
            children = _matching_children(node, segment, pointer, field)
            if not children:
                raise ScenarioContractError(f"Normalization path '{pointer}' did not match expected.")
            if is_last:
                matches.extend(children)
            else:
                next_nodes.extend(child.value for child in children)
        current = next_nodes

    if not matches:
        raise ScenarioContractError(f"Normalization path '{pointer}' did not match expected.")
    return matches


def _matching_children(node: object, segment: str, pointer: str, field: str) -> list[_Match]:
    if isinstance(node, dict):
        if not all(isinstance(key, str) for key in node):
            raise ScenarioContractError("Canonical expected objects must use string keys.")
        typed_node = cast(dict[str, object], node)
        if segment == "*":
            return [_Match(typed_node, key) for key in sorted(typed_node)]
        if segment not in typed_node:
            raise ScenarioContractError(f"Normalization path '{pointer}' did not match expected.")
        return [_Match(typed_node, segment)]

    if isinstance(node, list):
        if segment == "*":
            return [_Match(node, index) for index in range(len(node))]
        try:
            index = int(segment)
        except ValueError as error:
            raise ScenarioContractError(
                f"Scenario field '{field}' must use an array index or wildcard at '{segment}'."
            ) from error
        if str(index) != segment or index < 0 or index >= len(node):
            raise ScenarioContractError(f"Normalization path '{pointer}' did not match expected.")
        return [_Match(node, index)]

    raise ScenarioContractError(f"Normalization path '{pointer}' traverses a scalar value.")


def _collection_sort_key(item: object, keys: list[str], collection_path: str) -> tuple[tuple[int, object], ...]:
    values: list[tuple[int, object]] = []
    for key in keys:
        matches = _resolve_matches(item, key, field=f"sort key for {collection_path}")
        if len(matches) != 1:
            raise ScenarioContractError(
                f"Sort key '{key}' for '{collection_path}' must resolve to one scalar value."
            )
        values.append(_sortable_scalar(matches[0].value, key, collection_path))
    return tuple(values)


def _sortable_scalar(value: object, key: str, collection_path: str) -> tuple[int, object]:
    if value is None:
        return 0, ""
    if type(value) is bool:
        return 1, value
    if type(value) is int:
        return 2, value
    if type(value) is float:
        if not math.isfinite(value):
            raise ScenarioContractError(f"Sort key '{key}' for '{collection_path}' must be a finite scalar.")
        return 2, value
    if isinstance(value, str):
        return 3, value
    raise ScenarioContractError(f"Sort key '{key}' for '{collection_path}' must resolve to a JSON scalar.")


def _validate_volatile_scalar(value: object, kind: str, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise ScenarioContractError(f"Volatile target '{path}' of kind '{kind}' must be a non-empty string.")
    if kind == "uuid":
        try:
            uuid.UUID(value)
        except ValueError as error:
            raise ScenarioContractError(f"Volatile target '{path}' is not a valid UUID.") from error
    elif kind == "instant":
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ScenarioContractError(f"Volatile target '{path}' is not a valid ISO-8601 instant.") from error
        if parsed.tzinfo is None:
            raise ScenarioContractError(f"Volatile target '{path}' must include a timezone offset.")
    return value


def _decode_pointer_segment(segment: str) -> str:
    return segment.replace("~1", "/").replace("~0", "~")
