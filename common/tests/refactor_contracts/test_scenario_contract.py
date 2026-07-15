from __future__ import annotations

from copy import deepcopy
from unittest import TestCase

from . import ScenarioContractError, normalize_scenario_expected, validate_scenario_v1


def _scenario(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schemaVersion": 1,
        "scenarioId": "sync.router.converges",
        "capability": "CAP-SYNC",
        "mode": "router",
        "actor": {
            "kind": "service",
            "role": "local_agent_service_identity",
            "restaurantRef": "restaurant:primary",
        },
        "input": {},
        "expected": {},
        "volatilePaths": [],
        "unorderedCollections": [],
    }
    value.update(overrides)
    return value


class ScenarioSchemaV1Tests(TestCase):
    def test_valid_envelope_is_accepted(self):
        scenario = _scenario(
            actor={
                "kind": "user",
                "role": "cashier",
                "restaurantRef": "restaurant:primary",
                "subjectRef": "user:cashier",
                "permissionCodes": ["pos.order.create"],
            }
        )

        validated = validate_scenario_v1(scenario)

        self.assertEqual(validated, scenario)
        self.assertIsNot(validated, scenario)

    def test_missing_unknown_and_unsupported_version_fail_stably(self):
        missing = _scenario()
        missing.pop("expected")
        with self.assertRaisesRegex(ScenarioContractError, "scenario.expected.*required"):
            validate_scenario_v1(missing)

        with self.assertRaisesRegex(ScenarioContractError, "Unsupported scenario schemaVersion 2"):
            validate_scenario_v1(_scenario(schemaVersion=2))

        with self.assertRaisesRegex(ScenarioContractError, "unsupported fields: surprise"):
            validate_scenario_v1(_scenario(surprise=True))

    def test_mode_actor_and_capability_are_bounded(self):
        with self.assertRaisesRegex(ScenarioContractError, "field 'mode' must be one of"):
            validate_scenario_v1(_scenario(mode="automatic"))
        with self.assertRaisesRegex(ScenarioContractError, "field 'actor.kind' must be one of"):
            validate_scenario_v1(
                _scenario(actor={"kind": "robot", "role": "cashier", "restaurantRef": "restaurant:primary"})
            )
        with self.assertRaisesRegex(ScenarioContractError, "field 'capability' has an invalid format"):
            validate_scenario_v1(_scenario(capability="sync"))

    def test_malformed_or_duplicate_normalization_paths_fail(self):
        cases = [
            (
                {"volatilePaths": [{"path": "generatedAt", "kind": "instant"}]},
                "absolute JSON Pointer",
            ),
            (
                {"volatilePaths": [{"path": "/orders/**/id", "kind": "uuid"}]},
                "unsupported wildcard",
            ),
            (
                {"volatilePaths": [{"path": "/orders/~2id", "kind": "uuid"}]},
                "invalid JSON Pointer escape",
            ),
            (
                {"volatilePaths": [{"path": "/generatedAt", "kind": "everything"}]},
                "kind' must be one of",
            ),
            (
                {
                    "volatilePaths": [
                        {"path": "/generatedAt", "kind": "instant"},
                        {"path": "/generatedAt", "kind": "instant"},
                    ]
                },
                "duplicate path '/generatedAt'",
            ),
            (
                {"unorderedCollections": [{"path": "/orders", "keys": []}]},
                "keys' must not be empty",
            ),
        ]
        for override, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ScenarioContractError, message):
                validate_scenario_v1(_scenario(**override))


class ScenarioNormalizerTests(TestCase):
    def test_nested_wildcards_sort_and_tokenize_deterministically(self):
        first_uuid = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        second_uuid = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
        scenario = _scenario(
            expected={
                "groups": [
                    {
                        "name": "second",
                        "events": [
                            {
                                "name": "B",
                                "id": second_uuid,
                                "operationId": "operation-b",
                                "sameOperationId": "operation-b",
                                "cursor": "cursor-b",
                                "generatedAt": "2026-07-15T10:01:00+05:00",
                            },
                            {
                                "name": "A",
                                "id": first_uuid,
                                "operationId": "operation-a",
                                "sameOperationId": "operation-a",
                                "cursor": "cursor-a",
                                "generatedAt": "2026-07-15T10:00:00+05:00",
                            },
                        ],
                    }
                ]
            },
            volatilePaths=[
                {"path": "/groups/*/events/*/id", "kind": "uuid"},
                {"path": "/groups/*/events/*/operationId", "kind": "operation_id"},
                {"path": "/groups/*/events/*/sameOperationId", "kind": "operation_id"},
                {"path": "/groups/*/events/*/cursor", "kind": "cursor"},
                {"path": "/groups/*/events/*/generatedAt", "kind": "instant"},
            ],
            unorderedCollections=[{"path": "/groups/*/events", "keys": ["/name"]}],
        )

        first = normalize_scenario_expected(scenario)
        second = normalize_scenario_expected(scenario)
        events = first["groups"][0]["events"]

        self.assertEqual(first, second)
        self.assertEqual([event["name"] for event in events], ["A", "B"])
        self.assertEqual(events[0]["id"], "<uuid:1>")
        self.assertEqual(events[1]["id"], "<uuid:2>")
        self.assertEqual(events[0]["operationId"], events[0]["sameOperationId"])
        self.assertNotEqual(events[0]["operationId"], events[1]["operationId"])
        self.assertEqual(events[0]["cursor"], "<cursor:1>")
        self.assertEqual(events[0]["generatedAt"], "<instant:1>")

    def test_undeclared_business_values_and_source_are_unchanged(self):
        expected = {
            "amount": 71000,
            "status": "closed",
            "channel": "zal",
            "orderNumber": 1582,
            "openedAt": "2026-07-15T09:00:00+05:00",
            "paidAt": "2026-07-15T09:30:00+05:00",
            "outbox": [{"operationId": "fixed-operation", "attempts": 2}],
        }
        scenario = _scenario(expected=expected)
        before = deepcopy(scenario)

        normalized = normalize_scenario_expected(scenario)

        self.assertEqual(normalized, expected)
        self.assertEqual(scenario, before)
        self.assertIsNot(normalized, expected)

    def test_collection_order_is_preserved_unless_declared(self):
        scenario = _scenario(expected={"orders": [{"number": 2}, {"number": 1}]})

        self.assertEqual(
            [order["number"] for order in normalize_scenario_expected(scenario)["orders"]],
            [2, 1],
        )

        scenario["unorderedCollections"] = [{"path": "/orders", "keys": ["/number"]}]
        self.assertEqual(
            [order["number"] for order in normalize_scenario_expected(scenario)["orders"]],
            [1, 2],
        )

    def test_sort_is_stable_and_does_not_remove_duplicates(self):
        scenario = _scenario(
            expected={"items": [{"key": "b", "value": 1}, {"key": "a", "value": 2}, {"key": "a", "value": 2}]},
            unorderedCollections=[{"path": "/items", "keys": ["/key", "/value"]}],
        )

        items = normalize_scenario_expected(scenario)["items"]

        self.assertEqual([item["key"] for item in items], ["a", "a", "b"])
        self.assertEqual(len(items), 3)

    def test_pointer_escaping_targets_only_the_declared_value(self):
        scenario = _scenario(
            expected={"metadata/key": {"generated~at": "2026-07-15T10:00:00Z"}, "other": "unchanged"},
            volatilePaths=[{"path": "/metadata~1key/generated~0at", "kind": "instant"}],
        )

        normalized = normalize_scenario_expected(scenario)

        self.assertEqual(normalized["metadata/key"]["generated~at"], "<instant:1>")
        self.assertEqual(normalized["other"], "unchanged")

    def test_missing_or_overlapping_targets_fail_instead_of_hiding_drift(self):
        with self.assertRaisesRegex(ScenarioContractError, "did not match expected"):
            normalize_scenario_expected(
                _scenario(
                    expected={"metadata": {}},
                    volatilePaths=[{"path": "/metadata/generatedAt", "kind": "instant"}],
                )
            )

        with self.assertRaisesRegex(ScenarioContractError, "declared more than once"):
            normalize_scenario_expected(
                _scenario(
                    expected={"event": {"operationId": "operation-a"}},
                    volatilePaths=[
                        {"path": "/event/operationId", "kind": "operation_id"},
                        {"path": "/event/*", "kind": "operation_id"},
                    ],
                )
            )

    def test_invalid_volatile_values_and_sort_targets_fail(self):
        cases = [
            (
                _scenario(expected={"id": "not-a-uuid"}, volatilePaths=[{"path": "/id", "kind": "uuid"}]),
                "not a valid UUID",
            ),
            (
                _scenario(
                    expected={"generatedAt": "2026-07-15T10:00:00"},
                    volatilePaths=[{"path": "/generatedAt", "kind": "instant"}],
                ),
                "must include a timezone offset",
            ),
            (
                _scenario(
                    expected={"orders": {"number": 1}},
                    unorderedCollections=[{"path": "/orders", "keys": ["/number"]}],
                ),
                "must resolve to an array",
            ),
            (
                _scenario(
                    expected={"orders": [{"key": {"nested": True}}]},
                    unorderedCollections=[{"path": "/orders", "keys": ["/key"]}],
                ),
                "must resolve to a JSON scalar",
            ),
        ]
        for scenario, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ScenarioContractError, message):
                normalize_scenario_expected(scenario)
