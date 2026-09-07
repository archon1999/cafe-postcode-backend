from copy import deepcopy
from django.test import TestCase

from apps.local_agents.models import LocalAgent, LocalAgentMutationInbox
from apps.local_agents.mutation_inbox import receive_and_apply, _hash
from apps.restaurants.models import Restaurant


class IndependentFiscalDependencyTests(TestCase):
    def setUp(self):
        restaurant = Restaurant.objects.create(name="Independent fiscal history")
        self.agent, _ = LocalAgent.issue_for_restaurant(restaurant=restaurant)
        self.applied = []

    def event(self, name, sequence, deps=(), fiscal=False, epoch="original-owner"):
        return {
            "operationId": name, "userId": "original-cashier", "eventVersion": 2,
            "ownerEpoch": epoch, "sequence": sequence, "dependsOn": list(deps),
            "method": "POST", "body": {},
            "path": "/api/v1/pos/billing/" + (
                "fiscal-shifts/close/" if fiscal else "shifts/current/close/"
            ),
        }

    def receive(self, operation, success=True):
        def apply(original):
            self.assertEqual(original, operation)
            if success:
                self.applied.append(original["operationId"])
            return {"ok": success, "status": 200 if success else 400}
        return receive_and_apply(agent=self.agent, operation=operation, apply=apply)

    def test_old_fiscal_chain_is_traversed_without_changing_or_applying_fiscal_history(self):
        business = self.event("paid", 1)
        z1 = self.event("old-z", 2, ["paid"], fiscal=True)
        z2 = self.event("later-z", 3, ["old-z"], fiscal=True)
        cash = self.event("cash-close", 4, ["later-z"])
        self.receive(business)
        self.receive(z1, success=False)
        self.receive(z2, success=False)
        originals = {row.operation_id: (deepcopy(row.operation), row.payload_hash)
                     for row in LocalAgentMutationInbox.objects.all()}
        result = self.receive(cash)
        self.assertTrue(result["applied"], result)
        self.assertEqual(self.applied, ["paid", "cash-close"])
        self.assertEqual({x["operationId"] for x in result["dependencyReconciliation"]}, {"old-z", "later-z"})
        for name, (original, digest) in originals.items():
            stored = LocalAgentMutationInbox.objects.get(operation_id=name)
            self.assertEqual((stored.operation, stored.payload_hash), (original, digest))
        stored = LocalAgentMutationInbox.objects.get(operation_id="cash-close")
        self.assertEqual(stored.depends_on, ["later-z"])
        self.assertEqual(stored.payload_hash, _hash(cash))
        self.assertEqual(stored.attempts.get().result["dependencyReconciliation"], result["dependencyReconciliation"])
        self.assertTrue(self.receive(cash)["applied"])
        self.assertEqual(self.applied, ["paid", "cash-close"])

    def test_unapplied_money_ancestor_is_still_required(self):
        self.receive(self.event("money", 1), success=False)
        self.receive(self.event("z", 2, ["money"], fiscal=True), success=False)
        cash = self.event("close", 3, ["z"])
        result = self.receive(cash)
        self.assertFalse(result["applied"])
        self.assertEqual(result["missingDependencies"], ["money"])
        self.assertNotIn("close", self.applied)
        self.receive(self.event("money", 1))
        self.assertTrue(self.receive(cash)["applied"])

    def test_unknown_different_owner_or_forward_dependencies_cannot_be_waived(self):
        cases = [("missing", None), ("other-owner", "other"), ("future", "original-owner")]
        for index, (name, epoch) in enumerate(cases):
            if epoch is not None:
                self.receive(self.event(name, 100 + index, fiscal=True, epoch=epoch), success=False)
            result = self.receive(self.event("close-" + name, index + 1, [name]))
            self.assertFalse(result["applied"], result)
            self.assertEqual(result["missingDependencies"], [name])

    def test_fiscal_to_fiscal_ordering_remains_required(self):
        self.receive(self.event("first-z", 1, fiscal=True), success=False)
        result = self.receive(self.event("next-z", 2, ["first-z"], fiscal=True))
        self.assertFalse(result["applied"])
        self.assertEqual(result["missingDependencies"], ["first-z"])
