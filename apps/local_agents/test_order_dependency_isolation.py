from copy import deepcopy
from unittest.mock import Mock, patch

from django.test import TestCase
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.local_agents.models import LocalAgent, LocalAgentMutationInbox
from apps.local_agents.mutation_inbox import receive_and_apply
from apps.restaurants.models import Restaurant
from apps.local_agents.mutations import LocalAgentMutationReceiveView
from rest_framework.test import APIRequestFactory


class OrderDependencyIsolationTests(TestCase):
    def setUp(self):
        self.agent, _ = LocalAgent.issue_for_restaurant(
            restaurant=Restaurant.objects.create(name="Order isolation")
        )
        self.applied = []

    def event(self, name, seq, order="a", deps=(), path=None, epoch="owner"):
        return {
            "operationId": name, "userId": "cashier", "eventVersion": 2,
            "ownerEpoch": epoch, "sequence": seq, "dependsOn": list(deps),
            "method": "POST", "body": {"amount": 1000},
            "path": path or f"/api/v1/pos/billing/orders/{order}/pay/",
        }

    def receive(self, event, success=True):
        def apply(original):
            self.assertEqual(original, event)
            if success:
                self.applied.append(original["operationId"])
            return {"ok": success, "status": 200 if success else 400}
        return receive_and_apply(agent=self.agent, operation=event, apply=apply)

    def test_legacy_other_order_dependency_is_audited_without_rewriting_or_duplicate_sale(self):
        first = self.event("a1", 1)
        self.receive(first, False)
        saved = LocalAgentMutationInbox.objects.get(operation_id="a1")
        before = (deepcopy(saved.operation), saved.payload_hash, saved.state)
        second = self.event("b1", 2, "b", ["a1"])
        result = self.receive(second)
        self.assertTrue(result["applied"], result)
        self.assertEqual(result["dependencyReconciliation"][0]["rule"], "independent_order_payment_v1")
        saved.refresh_from_db()
        self.assertEqual((saved.operation, saved.payload_hash, saved.state), before)
        self.assertTrue(self.receive(second)["applied"])
        self.assertEqual(self.applied, ["b1"])
        self.assertEqual(LocalAgentMutationInbox.objects.get(operation_id="b1").depends_on, ["a1"])

    def test_same_order_ancestor_behind_another_order_is_still_required(self):
        self.receive(self.event("a1", 1), False)
        self.receive(self.event("b1", 2, "b", ["a1"]), False)
        result = self.receive(self.event("a2", 3, "a", ["b1"]))
        self.assertFalse(result["applied"])
        self.assertEqual(result["missingDependencies"], ["a1"])

    def test_applied_other_order_does_not_hide_unresolved_ancestor_from_same_order_or_close(self):
        self.receive(self.event("a1", 1), False)
        self.assertTrue(self.receive(self.event("b1", 2, "b", ["a1"]))["applied"])
        self.assertTrue(self.receive(self.event("c1", 3, "c", ["b1"]))["applied"])
        for event in (
            self.event("a2", 4, "a", ["c1"]),
            self.event("close", 5, deps=["c1"], path="/api/v1/pos/billing/shifts/current/close/"),
        ):
            result = self.receive(event)
            self.assertFalse(result["applied"], result)
            self.assertEqual(result["missingDependencies"], ["a1"])

    def test_shift_refund_expense_barriers_cannot_be_bypassed(self):
        for index, path in enumerate(("shifts/open/", "shifts/current/close/", "a/refund/", "shifts/current/expenses/")):
            with self.subTest(path=path):
                barrier = self.event(f"barrier-{index}", index * 3 + 1, path="/api/v1/pos/billing/" + path)
                self.receive(barrier, False)
                sale = self.event(f"a-{index}", index * 3 + 2, deps=[barrier["operationId"]])
                self.receive(sale, False)
                result = self.receive(self.event(f"b-{index}", index * 3 + 3, "b", [sale["operationId"]]))
                self.assertFalse(result["applied"])
                self.assertEqual(result["missingDependencies"], [barrier["operationId"]])

    def test_close_requires_all_payments_and_missing_or_other_owner_never_grants_waiver(self):
        self.receive(self.event("a1", 1), False)
        close = self.event("close", 2, deps=["a1"], path="/api/v1/pos/billing/shifts/current/close/")
        self.assertFalse(self.receive(close)["applied"])
        self.assertFalse(self.receive(self.event("missing", 3, "b", ["not-received"]))["applied"])
        self.assertFalse(self.receive(self.event("owner", 1, "b", ["a1"], epoch="other"))["applied"])
        self.receive(self.event("future", 100), False)
        self.assertFalse(self.receive(self.event("forward", 4, "b", ["future"]))["applied"])

    def test_settled_history_certificate_keeps_query_cost_bounded(self):
        parent = None
        for index in range(1, 130):
            event = self.event(str(index), index, format(index, "x"), [parent] if parent else [])
            self.assertTrue(self.receive(event)["applied"])
            parent = event["operationId"]
        with CaptureQueriesContext(connection) as captured:
            result = self.receive(self.event("last", 130, "ffff", [parent]))
        self.assertTrue(result["applied"])
        self.assertLess(len(captured), 25, "each sale must not scan the entire shift history")
        self.assertEqual(result["deferredOrderDependencies"], [])

    def test_same_order_successor_carries_unresolved_other_order_frontier_to_close(self):
        self.receive(self.event("b1", 1, "b"), False)
        self.assertTrue(self.receive(self.event("a1", 2, "a", ["b1"]))["applied"])
        successor = self.receive(self.event("a2", 3, "a", ["a1"]))
        self.assertTrue(successor["applied"])
        self.assertEqual(successor["deferredOrderDependencies"], ["b1"])
        closing = self.receive(self.event("close", 4, deps=["a2"], path="/api/v1/pos/billing/shifts/current/close/"))
        self.assertFalse(closing["applied"])
        self.assertEqual(closing["missingDependencies"], ["b1"])

    def test_intake_only_keeps_blocked_payment_original_without_executing_it(self):
        original = self.event("never-uploaded", 1)
        apply = Mock(side_effect=AssertionError("intake must not execute a sale"))
        result = receive_and_apply(agent=self.agent, operation=original, apply=apply, receive_only=True)
        self.assertTrue(result["durablyReceived"])
        self.assertFalse(result["applied"])
        apply.assert_not_called()
        self.assertEqual(LocalAgentMutationInbox.objects.get(operation_id="never-uploaded").operation, original)
        self.assertTrue(self.receive(self.event("independent", 2, "b", ["never-uploaded"]))["applied"])
        self.assertEqual(self.applied, ["independent"])
        self.assertTrue(self.receive(original)["applied"])
        self.assertTrue(self.receive(original)["applied"])
        self.assertEqual(self.applied, ["independent", "never-uploaded"])
        conflict = {**original, "body": {"amount": 9999}}
        self.assertEqual(receive_and_apply(agent=self.agent, operation=conflict, apply=apply, receive_only=True)["inboxState"], "conflict")

    def test_intake_http_requires_agent_auth_and_never_dispatches_business_mutation(self):
        factory = APIRequestFactory()
        payload = {"operations": [self.event("intake", 1)]}
        view = LocalAgentMutationReceiveView.as_view()
        with patch("apps.local_agents.mutations.authenticate_local_agent", return_value=None):
            response = view(factory.post("/sync/mutations/receive/", payload, format="json"))
        self.assertEqual(response.status_code, 401)
        with patch("apps.local_agents.mutations.authenticate_local_agent", return_value=self.agent), patch("apps.local_agents.mutation_processor.LocalAgentMutationProcessor._apply_operation") as apply:
            response = view(factory.post("/sync/mutations/receive/", payload, format="json"))
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.data["results"][0]["applied"])
            apply.assert_not_called()
