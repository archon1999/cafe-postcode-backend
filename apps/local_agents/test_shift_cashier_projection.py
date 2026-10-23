import copy
import uuid
from datetime import timedelta
from unittest.mock import patch

from django.utils import timezone
from djangorestframework_camel_case.util import underscoreize
from rest_framework.response import Response

from apps.billing.models import CashShift
from apps.local_agents.models import LocalAgent, LocalAgentMutationInbox
from apps.local_agents.tests_support import bind_agent_client
from apps.restaurants.models import CashDesk, Restaurant
from apps.sales.tests.support.pos_api import PosAPITestCase
from apps.users.models import User


class ShiftCashierProjectionTests(PosAPITestCase):
    def setUp(self):
        super().setUp()
        self.agent, self.token = LocalAgent.issue_for_restaurant(restaurant=self.restaurant)
        bind_agent_client(self.client, self.agent, self.token)
        self.other_desk = CashDesk.objects.create(restaurant=self.restaurant, name="Second desk")
        self.shift_id = uuid.uuid4()
        self.opened_at = timezone.now() - timedelta(hours=2)

    def operation(self):
        return {
            "operationId": "shift-cashier:" + str(uuid.uuid4()),
            "userId": str(self.user.pk),
            "method": "POST",
            "path": "/api/v1/pos/billing/shifts/open/",
            "occurredAt": self.opened_at.isoformat(),
            "body": {
                "edgeCashShiftId": str(self.shift_id),
                "edgeCashShiftOpenedAt": self.opened_at.isoformat(),
                "cashDeskId": str(self.cash_desk.pk),
                "cashierId": str(self.user.pk),
                "openingCashAmount": 12000,
            },
        }

    def push(self, operation):
        response = self.client.post(
            "/api/v1/local-agent/sync/mutations/", {"operations": [operation]},
            format="json", HTTP_AUTHORIZATION=f"Bearer {self.token}",
        )
        self.assertEqual(response.status_code, 200, response.data)
        return response.data["results"][0]

    def assert_original_shift(self):
        shift = CashShift.objects.get(pk=self.shift_id)
        self.assertEqual(shift.cashier_id, self.user.pk)
        self.assertEqual(shift.opened_by_id, self.user.pk)
        self.assertEqual(shift.cash_desk_id, self.cash_desk.pk)
        self.assertEqual(shift.opened_at, self.opened_at)
        self.assertEqual(shift.opening_cash_amount, 12000)
        self.assertEqual(shift.status, CashShift.Status.OPEN)
        self.assertEqual(CashShift.objects.filter(cash_desk=self.cash_desk).count(), 1)

    def test_identified_manager_shift_preserves_cashier_and_is_idempotent(self):
        operation = self.operation()
        original = copy.deepcopy(operation)
        for payload in (operation, underscoreize(operation)):
            result = self.push(payload)
            self.assertTrue(result["ok"], result)
            self.assertTrue(result["applied"], result)
            self.assert_original_shift()
        self.assertTrue(result["replayed"])
        self.assertEqual(operation, original)
        inbox = LocalAgentMutationInbox.objects.get(operation_id=operation["operationId"])
        self.assertEqual(inbox.operation["body"]["cashier_id"], str(self.user.pk))

    def test_identified_shift_without_selected_cashier_matches_agent_opening_user(self):
        operation = self.operation()
        del operation["body"]["cashierId"]
        result = self.push(operation)
        self.assertTrue(result["ok"], result)
        self.assert_original_shift()

    def test_previously_rejected_evidence_can_be_retried_without_changing_identity(self):
        operation = self.operation()

        # Retain the original evidence with the historical rejection, then
        # exercise the real replay path against the corrected view.
        with patch("apps.billing.api.pos.views.context.CashShiftOpenView.post", return_value=Response(
            {"cashierId": ["Cashier selection is required."]}, status=400,
        )):
            rejected = self.push(operation)
        self.assertFalse(rejected["ok"])
        inbox = LocalAgentMutationInbox.objects.get(operation_id=operation["operationId"])
        original_hash = inbox.payload_hash
        original_evidence = copy.deepcopy(inbox.operation)
        self.assertEqual(inbox.state, "needs_review")
        self.assertFalse(CashShift.objects.filter(pk=self.shift_id).exists())
        result = self.push(operation)
        self.assertTrue(result["ok"], result)
        self.assert_original_shift()
        inbox.refresh_from_db()
        self.assertEqual(inbox.state, "applied")
        self.assertEqual(inbox.payload_hash, original_hash)
        self.assertEqual(inbox.operation, original_evidence)

    def test_foreign_cashier_is_rejected(self):
        restaurant = Restaurant.objects.create(name="Other restaurant")
        foreign = User.objects.create_user(username="foreign-shift-cashier", restaurant=restaurant, role=self.role)
        operation = self.operation()
        operation["body"]["cashierId"] = str(foreign.pk)
        result = self.push(operation)
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["status"], 400)
        self.assertFalse(CashShift.objects.filter(pk=self.shift_id).exists())

    def test_unidentified_legacy_shift_still_requires_cashier_with_multiple_desks(self):
        operation = self.operation()
        del operation["body"]["edgeCashShiftId"]
        result = self.push(operation)
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["status"], 400)
        self.assertFalse(CashShift.objects.filter(cash_desk=self.cash_desk).exists())
