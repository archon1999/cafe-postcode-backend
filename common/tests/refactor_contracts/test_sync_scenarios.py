import uuid

from rest_framework import status

from apps.local_agents.models import LocalAgent, LocalAgentMutationReceipt
from apps.local_agents.mutations import _request_hash
from apps.sales.models import Order
from apps.sales.tests.support.pos_api import PosAPITestCase


class BackendMutationSyncScenarioTests(PosAPITestCase):
    mutation_url = "/api/v1/local-agent/sync/mutations/"

    def setUp(self):
        super().setUp()
        _agent, self.agent_token = LocalAgent.issue_for_restaurant(
            restaurant=self.restaurant,
            name="Sync characterization agent",
        )

    def push(self, *operations):
        response = self.client.post(
            self.mutation_url,
            {"operations": list(operations)},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {self.agent_token}",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        return response.data["results"]

    def order_create(self, *, operation_id, order_id=None, note="offline order"):
        return {
            "operationId": operation_id,
            "userId": str(self.user.id),
            "method": "POST",
            "path": "/api/v1/pos/sales/orders/",
            "body": {
                "id": str(order_id or uuid.uuid4()),
                "channel": Order.Channel.TAKEAWAY,
                "guestCount": 1,
                "note": note,
            },
        }

    def test_identical_operation_replay_returns_stored_result_once(self):
        order_id = uuid.uuid4()
        operation = self.order_create(
            operation_id="sync-characterization-order-create",
            order_id=order_id,
        )

        first = self.push(operation)[0]
        replay = self.push(operation)[0]

        self.assertEqual(first["status"], status.HTTP_201_CREATED)
        self.assertFalse(first["replayed"])
        self.assertEqual(replay["status"], first["status"])
        self.assertEqual(replay["body"], first["body"])
        self.assertTrue(replay["replayed"])
        self.assertFalse(replay["retryable"])
        self.assertEqual(Order.objects.filter(id=order_id).count(), 1)
        self.assertEqual(
            LocalAgentMutationReceipt.objects.filter(
                operation_id=operation["operationId"]
            ).count(),
            1,
        )

    def test_operation_id_collision_is_terminal_and_does_not_apply_second_write(self):
        operation_id = "sync-characterization-collision"
        first_order_id = uuid.uuid4()
        second_order_id = uuid.uuid4()
        first_operation = self.order_create(
            operation_id=operation_id,
            order_id=first_order_id,
            note="first payload",
        )
        colliding_operation = self.order_create(
            operation_id=operation_id,
            order_id=second_order_id,
            note="different payload",
        )

        first = self.push(first_operation)[0]
        collision = self.push(colliding_operation)[0]

        self.assertEqual(first["status"], status.HTTP_201_CREATED)
        self.assertEqual(
            collision,
            {
                "operationId": operation_id,
                "ok": False,
                "status": status.HTTP_409_CONFLICT,
                "error": "operationId already belongs to another mutation.",
                "retryable": False,
            },
        )
        self.assertTrue(Order.objects.filter(id=first_order_id).exists())
        self.assertFalse(Order.objects.filter(id=second_order_id).exists())
        self.assertEqual(
            LocalAgentMutationReceipt.objects.filter(operation_id=operation_id).count(),
            1,
        )

    def test_missing_order_item_delete_converges_to_durable_success(self):
        operation = {
            "operationId": "sync-characterization-missing-delete",
            "userId": str(self.user.id),
            "method": "DELETE",
            "path": f"/api/v1/pos/sales/orders/items/{uuid.uuid4()}/",
            "body": {},
        }

        result = self.push(operation)[0]
        replay = self.push(operation)[0]

        self.assertEqual(result["status"], status.HTTP_204_NO_CONTENT)
        self.assertTrue(result["ok"])
        self.assertTrue(result["reconciled"])
        self.assertEqual(result["body"]["reason"], "already_absent")
        self.assertEqual(replay["status"], status.HTTP_204_NO_CONTENT)
        self.assertTrue(replay["ok"])
        self.assertTrue(replay["replayed"])
        receipt = LocalAgentMutationReceipt.objects.get(
            operation_id=operation["operationId"]
        )
        self.assertEqual(receipt.response_status, status.HTTP_204_NO_CONTENT)
        self.assertEqual(receipt.response_body["reason"], "already_absent")

    def test_legacy_closed_order_delete_is_upgraded_to_durable_success(self):
        item_id = uuid.uuid4()
        operation = {
            "operationId": "sync-characterization-legacy-closed-delete",
            "userId": str(self.user.id),
            "method": "DELETE",
            "path": f"/api/v1/pos/sales/orders/items/{item_id}/",
            "body": {},
        }
        receipt = LocalAgentMutationReceipt.objects.create(
            restaurant=self.restaurant,
            operation_id=operation["operationId"],
            user_id=self.user.id,
            method=operation["method"],
            path=operation["path"],
            request_hash=_request_hash(
                user_id=str(self.user.id),
                method=operation["method"],
                path=operation["path"],
                body=operation["body"],
            ),
            response_status=status.HTTP_400_BAD_REQUEST,
            response_body={"detail": "Closed or cancelled orders cannot be modified."},
        )

        reconciled = self.push(operation)[0]
        replay = self.push(operation)[0]

        self.assertEqual(reconciled["status"], status.HTTP_204_NO_CONTENT)
        self.assertTrue(reconciled["ok"])
        self.assertTrue(reconciled["replayed"])
        self.assertTrue(reconciled["reconciled"])
        self.assertEqual(reconciled["body"]["reason"], "order_already_finalized")
        self.assertEqual(replay["status"], status.HTTP_204_NO_CONTENT)
        self.assertTrue(replay["ok"])
        self.assertTrue(replay["replayed"])
        receipt.refresh_from_db()
        self.assertEqual(receipt.response_status, status.HTTP_204_NO_CONTENT)
        self.assertEqual(receipt.response_body["reason"], "order_already_finalized")
